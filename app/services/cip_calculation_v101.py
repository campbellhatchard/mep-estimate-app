from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session

from ..cip_models import CIPRevisionInput
from ..models import CalculationAdjustment, EstimateRevision
from .cip_detail_engine import CIPConfig, xrnd as workbook_round
from .cip_phase_engine import calculation as legacy_calculation

CIP_ENGINE_VERSION = "CIP-1.0.1"
LOCKED_STATUSES = {"APPROVED", "FINAL", "SUPERSEDED"}


def q2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculation(db: Session, rev: EstimateRevision):
    # Locked historical revisions retain their original CIP-1.0.0 commercial result.
    if rev.status in LOCKED_STATUSES and rev.engine_version != CIP_ENGINE_VERSION:
        return legacy_calculation(db, rev)

    lines, summary, details, detail_summary = legacy_calculation(db, rev)
    inp = db.get(CIPRevisionInput, rev.id)
    if not inp:
        return lines, summary, details, detail_summary
    cfg = CIPConfig(db, rev.config_version_id)
    adjustments = {
        row.line_key: float(row.adjust_hours or 0)
        for row in db.query(CalculationAdjustment)
        .filter(CalculationAdjustment.revision_id == rev.id)
        .all()
    }
    by_key = {line.key: line for line in lines}
    contingency_factor = cfg.param("SMALL_PROJECT_CONTINGENCY_FACTOR") if inp.project_type == "Small Project" else cfg.param("CONTINGENCY_FACTOR")

    def adjust(key: str) -> float:
        return adjustments.get(key, 0.0)

    def set_hours(key: str, investment: float):
        row = by_key.get(key)
        if not row:
            return
        row.investment_hours = q2(investment)
        row.task_hours = q2(row.investment_hours + float(row.non_billable_hours or 0))

    # Plan overhead follows the workbook formula, then applies the estimator's manual
    # adjustment exactly. Prep Extended/Investment is based on adjusted child investment.
    plan_direct = [
        row for row in lines
        if row.phase == "Plan" and row.key not in {"PLAN_PM", "PLAN_CONTINGENCY", "PLAN_PREP"}
    ]
    plan_standard_base = sum(float(row.standard_hours or 0) for row in plan_direct)
    plan_investment_base = sum(float(row.investment_hours or 0) for row in plan_direct)
    plan_nonbillable_base = sum(float(row.non_billable_hours or 0) for row in plan_direct)
    set_hours("PLAN_PREP", workbook_round(plan_investment_base * cfg.param("PREP_FACTOR"), 0) + adjust("PLAN_PREP"))
    set_hours("PLAN_PM", workbook_round((plan_investment_base + plan_nonbillable_base) * cfg.param("IM_FACTOR"), 0) + adjust("PLAN_PM"))
    set_hours("PLAN_CONTINGENCY", workbook_round(plan_investment_base * contingency_factor, 0) + adjust("PLAN_CONTINGENCY"))

    # Other phase overheads are similarly rounded as formula outputs first, then the
    # manual Standard Adjust value is added without being rounded away.
    for phase, prefix in [("Design", "DESIGN"), ("Build", "BUILD"), ("Test", "TEST"), ("Go Live", "GOLIVE")]:
        pm_key = f"{prefix}_PM"
        cont_key = f"{prefix}_CONTINGENCY"
        direct = [row for row in lines if row.phase == phase and row.key not in {pm_key, cont_key}]
        investment_base = sum(float(row.investment_hours or 0) for row in direct)
        set_hours(pm_key, workbook_round(investment_base * cfg.param("IM_FACTOR"), 0) + adjust(pm_key))
        set_hours(cont_key, workbook_round(investment_base * contingency_factor, 0) + adjust(cont_key))

    phase_totals = {}
    for phase in ["Plan", "Design", "Build", "Test", "Go Live"]:
        rows = [row for row in lines if row.phase == phase]
        phase_totals[phase] = {
            "standard": q2(sum(float(row.standard_hours or 0) for row in rows)),
            "investment": q2(sum(float(row.investment_hours or 0) for row in rows)),
            "non_billable": q2(sum(float(row.non_billable_hours or 0) for row in rows)),
            "task": q2(sum(float(row.task_hours or 0) for row in rows)),
        }

    investment_hours = q2(sum(value["investment"] for value in phase_totals.values()))
    non_billable_hours = q2(sum(value["non_billable"] for value in phase_totals.values()))
    total_internal_hours = q2(investment_hours + non_billable_hours)
    billing_rate = float(rev.billing_rate or 0)
    low_hours = q2(investment_hours * (1 - inp.low_factor))
    high_hours = q2(investment_hours * (1 + inp.high_factor))
    duration = q2((investment_hours / cfg.param("DURATION_HOURS_PER_MONTH")) * cfg.param("DURATION_FACTOR")) if investment_hours else 0.0

    summary.update({
        "hours": investment_hours,
        "investment_hours": investment_hours,
        "non_billable_hours": non_billable_hours,
        "total_internal_hours": total_internal_hours,
        "fees": q2(investment_hours * billing_rate),
        "low_hours": low_hours,
        "high_hours": high_hours,
        "low_fees": q2(low_hours * billing_rate),
        "high_fees": q2(high_hours * billing_rate),
        "duration_months": duration,
        "phase_totals": phase_totals,
    })
    return lines, summary, details, detail_summary


def recalculate_and_store(db: Session, rev: EstimateRevision):
    if rev.status in LOCKED_STATUSES and rev.engine_version != CIP_ENGINE_VERSION:
        return legacy_calculation(db, rev)
    lines, summary, details, detail_summary = calculation(db, rev)
    rev.calculated_hours = summary["investment_hours"]
    rev.calculated_fees = summary["fees"]
    rev.low_hours = summary["low_hours"]
    rev.high_hours = summary["high_hours"]
    rev.duration_months = summary["duration_months"]
    rev.engine_version = CIP_ENGINE_VERSION
    db.flush()
    return lines, summary, details, detail_summary

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session

from ..cip_models import CIPNonBillableAllocation, CIPRevisionInput
from ..models import EstimateRevision
from .cip_detail_engine import CIPConfig, xrnd
from .cip_calculation_v101 import calculation as calculation_v101


CIP_ENGINE_VERSION = "CIP-1.0.2"
LOCKED_STATUSES = {"APPROVED", "FINAL", "SUPERSEDED"}


def q2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculation(db: Session, rev: EstimateRevision):
    """Calculate gross effort first, then apply investment as funding allocation.

    CIP-1.0.2 changes the commercial meaning of the persisted allocation rows:
    allocation hours are internally funded Investment Hours inside already-calculated
    Task Hours. They do not add effort and therefore cannot change PM, contingency,
    preparation, testing, schedule effort, duration, or any other effort-derived line.

    Locked historical revisions remain on their pinned earlier engine semantics.
    """
    if rev.status in LOCKED_STATUSES and rev.engine_version != CIP_ENGINE_VERSION:
        return calculation_v101(db, rev)

    inp = db.get(CIPRevisionInput, rev.id)
    if not inp:
        raise KeyError(f"CIP inputs missing for revision {rev.id}")
    cfg = CIPConfig(db, rev.config_version_id)

    allocations = (
        db.query(CIPNonBillableAllocation)
        .filter(CIPNonBillableAllocation.revision_id == rev.id)
        .all()
    )
    allocation_hours = {row.line_key: q2(float(row.hours or 0)) for row in allocations}

    # V1.0.1 treated these rows as additive Plan effort. Suppress the allocations while
    # calculating the gross effort model, then restore the session state and apply them
    # solely as a funding split. no_autoflush prevents temporary zeroes from persisting.
    original_hours = {row.id: row.hours for row in allocations}
    for row in allocations:
        row.hours = 0
    try:
        with db.no_autoflush:
            lines, summary, details, detail_summary = calculation_v101(db, rev)
    finally:
        for row in allocations:
            row.hours = original_hours[row.id]

    for line in lines:
        gross_task = q2(float(line.task_hours or line.investment_hours or 0))
        investment = q2(allocation_hours.get(line.key, 0.0))
        if investment < 0:
            raise ValueError(f"Investment Hours cannot be negative for {line.description}.")
        if investment > gross_task:
            raise ValueError(
                f"Investment Hours ({investment:g}) cannot exceed Task Hours "
                f"({gross_task:g}) for {line.description}."
            )
        billable = q2(gross_task - investment)

        # Preserve the stable line object while correcting the commercial semantics.
        line.task_hours = gross_task
        line.investment_hours = investment
        line.non_billable_hours = investment  # backward-compatible persisted/export alias
        line.billable_hours = billable

    phase_totals = {}
    for phase in ["Plan", "Design", "Build", "Test", "Go Live"]:
        rows = [row for row in lines if row.phase == phase]
        phase_investment = q2(sum(float(row.investment_hours or 0) for row in rows))
        phase_totals[phase] = {
            "standard": q2(sum(float(row.standard_hours or 0) for row in rows)),
            "task": q2(sum(float(row.task_hours or 0) for row in rows)),
            "investment": phase_investment,
            "billable": q2(sum(float(row.billable_hours or 0) for row in rows)),
            "non_billable": phase_investment,
        }

    task_hours = q2(sum(value["task"] for value in phase_totals.values()))
    investment_hours = q2(sum(value["investment"] for value in phase_totals.values()))
    billable_hours = q2(sum(value["billable"] for value in phase_totals.values()))
    billing_rate = float(rev.billing_rate or 0)

    # Estimate range and duration remain effort-derived. Preserve the source-model whole-hour
    # range rounding, then apply the fixed approved funding allocation to each billable range.
    low_task_hours = xrnd(task_hours * (1 - inp.low_factor), 0)
    high_task_hours = xrnd(task_hours * (1 + inp.high_factor), 0)
    low_billable_hours = q2(max(0.0, low_task_hours - investment_hours))
    high_billable_hours = q2(max(0.0, high_task_hours - investment_hours))
    duration = xrnd(
        (task_hours / cfg.param("DURATION_HOURS_PER_MONTH")) * cfg.param("DURATION_FACTOR"),
        2,
    ) if task_hours else 0.0

    summary.update({
        "hours": billable_hours,
        "task_hours": task_hours,
        "investment_hours": investment_hours,
        "billable_hours": billable_hours,
        "non_billable_hours": investment_hours,  # compatibility alias
        "total_internal_hours": task_hours,
        "fees": q2(billable_hours * billing_rate),
        "low_task_hours": low_task_hours,
        "high_task_hours": high_task_hours,
        "low_billable_hours": low_billable_hours,
        "high_billable_hours": high_billable_hours,
        "low_hours": low_billable_hours,
        "high_hours": high_billable_hours,
        "low_fees": q2(low_billable_hours * billing_rate),
        "high_fees": q2(high_billable_hours * billing_rate),
        "duration_months": duration,
        "phase_totals": phase_totals,
    })
    return lines, summary, details, detail_summary


def recalculate_and_store(db: Session, rev: EstimateRevision):
    if rev.status in LOCKED_STATUSES and rev.engine_version != CIP_ENGINE_VERSION:
        return calculation_v101(db, rev)
    lines, summary, details, detail_summary = calculation(db, rev)
    rev.calculated_hours = summary["billable_hours"]
    rev.calculated_fees = summary["fees"]
    rev.low_hours = summary["low_billable_hours"]
    rev.high_hours = summary["high_billable_hours"]
    rev.duration_months = summary["duration_months"]
    rev.engine_version = CIP_ENGINE_VERSION
    db.flush()
    return lines, summary, details, detail_summary


def install_cip_investment_funding(core) -> None:
    """Install CIP-1.0.2 before route/explanation closures capture calculation bindings."""
    from . import cip_calculation as cip_public_module
    from . import cip_schedule as cip_schedule_module
    from .. import (
        calculation_explain,
        cip_domain,
        cip_revision,
        cip_routes_detail,
        cip_routes_estimate,
        cip_routes_exports,
        precision_runtime,
    )

    cip_public_module.calculation = calculation
    cip_public_module.recalculate_and_store = recalculate_and_store
    cip_public_module.CIP_ENGINE_VERSION = CIP_ENGINE_VERSION
    cip_schedule_module.calculation = calculation
    cip_domain.cip_calculation = calculation
    cip_domain.cip_recalculate_and_store = recalculate_and_store
    cip_revision.cip_recalculate_and_store = recalculate_and_store
    cip_revision.CIP_ENGINE_VERSION = CIP_ENGINE_VERSION
    cip_routes_estimate.cip_recalculate_and_store = recalculate_and_store
    cip_routes_detail.cip_calculation = calculation
    cip_routes_detail.cip_recalculate_and_store = recalculate_and_store
    cip_routes_exports.cip_calculation = calculation

    # precision_runtime owns preview/PDF/startup closures and captured the prior versioned
    # functions at import time. Patch those module globals before the routes are registered.
    precision_runtime.cip_calculation = calculation
    precision_runtime.cip_recalculate = recalculate_and_store
    precision_runtime.CIP_ENGINE_VERSION = CIP_ENGINE_VERSION

    # Keep Explain evidence commercially accurate without changing its formula/config detail.
    original_enrich = calculation_explain.enrich_cip_lines
    if not getattr(original_enrich, "_cip_funding_semantics", False):
        def funding_enrich(db, rev, lines):
            enriched = original_enrich(db, rev, lines)
            if rev.engine_version == CIP_ENGINE_VERSION:
                for line in enriched:
                    old = (
                        f"Plan Hours Not Billable ({line.non_billable_hours}) affect internal "
                        "Task Hours but not customer Investment Hours."
                    )
                    new = (
                        f"Investment Hours ({line.investment_hours}) are an internal funding "
                        f"allocation within gross Task Hours; Customer Billable Hours are "
                        f"{line.billable_hours}. Investment does not change gross effort or "
                        "effort-derived PM, contingency, preparation, testing or schedule effort."
                    )
                    line.trace = (line.trace or "").replace(old, new)
                    line.trace = line.trace.replace(
                        "adjusted build-scope investment", "adjusted gross build Task Hours"
                    ).replace(
                        "phase child investment", "phase child gross Task Hours"
                    )
            return enriched

        funding_enrich._cip_funding_semantics = True
        calculation_explain.enrich_cip_lines = funding_enrich

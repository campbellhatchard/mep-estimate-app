from __future__ import annotations

import io
from decimal import Decimal

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from .models import CalculationAdjustment, ConfigurationVersion, EstimateRevision
from .cip_models import CIPNonBillableAllocation, PRODUCT_CIP, PRODUCT_MEP
from .cip_domain import revision_product
from .route_architecture import remove_route
from .services.audit import record
from .services.calculation_v101 import (
    ENGINE_VERSION as MEP_ENGINE_VERSION,
    calculation as mep_calculation,
    recalculate_and_store as mep_recalculate,
)
from .services.cip_calculation_v101 import (
    CIP_ENGINE_VERSION,
    calculation as cip_calculation,
    recalculate_and_store as cip_recalculate,
)

LOCKED = {"APPROVED", "FINAL", "SUPERSEDED"}


def format_hours(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return str(value)
    text = format(number, "f").rstrip("0").rstrip(".")
    return text or "0"


def consistent_format(fmt, *args, **kwargs):
    # Standardize plain numeric rendering without changing percentages, dates or currency.
    if not kwargs and len(args) == 1 and fmt in {"%.0f", "%.1f", "%.2f"}:
        return format_hours(args[0])
    if kwargs:
        return fmt % kwargs
    return fmt % args


def install_calculation_precision(core):
    # Patch legacy MEP module globals used by existing route closures.
    core.calculation = mep_calculation
    core.recalculate_and_store = mep_recalculate
    core.ENGINE_VERSION = MEP_ENGINE_VERSION

    from .services import schedule as mep_schedule_module
    mep_schedule_module.calculation = mep_calculation

    # Patch every already-imported CIP module that captured function references at import time.
    from .services import cip_calculation as cip_public_module
    from .services import cip_schedule as cip_schedule_module
    from . import cip_domain, cip_revision, cip_routes_estimate, cip_routes_detail, cip_routes_exports

    cip_public_module.calculation = cip_calculation
    cip_public_module.recalculate_and_store = cip_recalculate
    cip_public_module.CIP_ENGINE_VERSION = CIP_ENGINE_VERSION
    cip_schedule_module.calculation = cip_calculation
    cip_domain.cip_calculation = cip_calculation
    cip_domain.cip_recalculate_and_store = cip_recalculate
    cip_revision.cip_recalculate_and_store = cip_recalculate
    cip_revision.CIP_ENGINE_VERSION = CIP_ENGINE_VERSION
    cip_routes_estimate.cip_recalculate_and_store = cip_recalculate
    cip_routes_detail.cip_calculation = cip_calculation
    cip_routes_detail.cip_recalculate_and_store = cip_recalculate
    cip_routes_exports.cip_calculation = cip_calculation

    core.templates.env.filters["format"] = consistent_format
    core.templates.env.filters["hours"] = format_hours


def _parse_adjustments(form) -> dict[str, float]:
    count = int(form.get("line_count", 0) or 0)
    values = {}
    for idx in range(count):
        key = str(form.get(f"line_key_{idx}", "")).strip()
        if not key:
            continue
        try:
            values[key] = float(form.get(f"adjust_{idx}", 0) or 0)
        except Exception:
            values[key] = 0.0
    return values


def register_precision_routes(app, core):
    @app.post("/estimate/{rid}/calculations/preview")
    async def calculation_preview(rid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
        rev = core.revision_or_404(db, rid)
        if rev.status in LOCKED:
            return JSONResponse({"detail": "Revision is locked"}, status_code=409)
        form = await request.form()
        adjustments = _parse_adjustments(form)

        if revision_product(db, rev) == PRODUCT_MEP:
            lines, summary, _, _ = mep_calculation(db, rev, adjustment_overrides=adjustments)
            return {
                "product": PRODUCT_MEP,
                "rows": [{"key": row.key, "standard": row.standard_hours, "extended": row.extended_hours} for row in lines],
                "phase_totals": summary["phase_totals"],
                "summary": {"hours": summary["hours"], "fees": summary["fees"]},
            }

        # CIP preview uses a request-local transaction. Unsaved values are applied to the
        # SQLAlchemy session, calculated, serialized, then rolled back so preview never persists.
        existing = {
            row.line_key: row
            for row in db.query(CalculationAdjustment)
            .filter(CalculationAdjustment.revision_id == rev.id)
            .all()
        }
        for key, value in adjustments.items():
            row = existing.get(key)
            if not row:
                row = CalculationAdjustment(revision_id=rev.id, line_key=key, adjust_hours=0, notes="")
                db.add(row)
                existing[key] = row
            row.adjust_hours = value

        count = int(form.get("line_count", 0) or 0)
        allocations = {
            row.line_key: row
            for row in db.query(CIPNonBillableAllocation)
            .filter(CIPNonBillableAllocation.revision_id == rev.id)
            .all()
        }
        for idx in range(count):
            key = str(form.get(f"line_key_{idx}", "")).strip()
            phase = str(form.get(f"phase_{idx}", "")).strip()
            if not key or phase != "Plan":
                continue
            try:
                hours = float(form.get(f"nonbillable_{idx}", 0) or 0)
            except Exception:
                hours = 0.0
            row = allocations.get(key)
            if not row:
                row = CIPNonBillableAllocation(revision_id=rev.id, line_key=key, hours=0, notes="")
                db.add(row)
                allocations[key] = row
            row.hours = max(0.0, hours)

        db.flush()
        lines, summary, _, _ = cip_calculation(db, rev)
        payload = {
            "product": PRODUCT_CIP,
            "rows": [{
                "key": row.key,
                "standard": row.standard_hours,
                "investment": row.investment_hours,
                "non_billable": row.non_billable_hours,
                "task": row.task_hours,
            } for row in lines],
            "phase_totals": summary["phase_totals"],
            "summary": {
                "investment_hours": summary["investment_hours"],
                "non_billable_hours": summary["non_billable_hours"],
                "total_internal_hours": summary["total_internal_hours"],
                "fees": summary["fees"],
            },
        }
        db.rollback()
        return payload

    # Replace the PDF route after product dispatch registration so HTML and PDF use the same
    # precision rules and historical calculation engine boundary.
    remove_route(app, "/estimate/{rid}/pdf", "GET")

    @app.get("/estimate/{rid}/pdf")
    def precision_pdf(rid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        rev = core.revision_or_404(db, rid)
        product = revision_product(db, rev)
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        story = []

        if product == PRODUCT_MEP:
            lines, summary, _, _ = mep_calculation(db, rev)
            story += [Paragraph("Cloud Inventory — MEP Services Estimate", styles["Title"]), Spacer(1, 12)]
            meta = [["Customer", rev.customer], ["Estimate", f"{rev.estimate.estimate_number} Rev {rev.revision_no}"], ["Opportunity", rev.opportunity_number], ["Proposal Date", str(rev.proposal_date or "")], ["Project Type", rev.project_type], ["ERP", rev.erp], ["Configuration", db.get(ConfigurationVersion, rev.config_version_id).name]]
            table = Table(meta, colWidths=[120, 360]); table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#d9edf7")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [table, Spacer(1, 14), Paragraph("Estimate Summary", styles["Heading2"])]
            data = [["Solution", "Hours", "Fees", "Duration"], ["Estimate", format_hours(summary["hours"]), f"{summary['fees']:,.2f}", f"{format_hours(summary['duration_months'])} Months"], ["Range Low", format_hours(summary["low_hours"]), f"{summary['low_fees']:,.2f}", ""], ["Range High", format_hours(summary["high_hours"]), f"{summary['high_fees']:,.2f}", ""]]
            table = Table(data, colWidths=[180, 80, 120, 120]); table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0089a8")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
            story += [table, Spacer(1, 14), Paragraph("Phase Summary", styles["Heading2"])]
            pdata = [["Phase", "Hours"]] + [[phase, format_hours(value["extended"])] for phase, value in summary["phase_totals"].items()]
            table = Table(pdata, colWidths=[300, 100]); table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey)])); story += [table, Spacer(1, 14)]
            selected = [a for a in rev.applications if a.config_type != "No Config"]
            if selected:
                story.append(Paragraph("Selected Applications / Packages", styles["Heading2"]))
                app_data = [["Type", "Definition", "Configuration"]] + [[a.kind.title(), a.label, a.config_type] for a in selected]
                app_table = Table(app_data, colWidths=[80, 300, 100]); app_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9edf7"))]))
                story += [app_table, Spacer(1, 12)]
            story.append(Paragraph("Assumptions", styles["Heading2"]))
            story.append(Paragraph(f"This estimate uses configuration {db.get(ConfigurationVersion, rev.config_version_id).name} and calculation engine {rev.engine_version}. Manual adjustments are retained in the application audit history.", styles["BodyText"]))
        else:
            _, summary, _, _ = cip_calculation(db, rev)
            from .cip_domain import _cip_input
            from .services.cip_detail_engine import CIPConfig
            inp = _cip_input(db, rid)
            cfg = CIPConfig(db, rev.config_version_id)
            release = cfg.item_by_key("CIP Release", inp.release_key)
            story += [Paragraph("Cloud Inventory Platform — Services Estimate", styles["Title"]), Spacer(1, 12)]
            meta = [["Customer", rev.customer], ["Estimate", f"{rev.estimate.estimate_number} Rev {rev.revision_no}"], ["Opportunity", rev.opportunity_number], ["Proposal Date", str(rev.proposal_date or "")], ["Project Type", inp.project_type], ["Deployed Over", inp.deployed_over], ["CIP Release", release.label if release else inp.release_key], ["Configuration", db.get(ConfigurationVersion, rev.config_version_id).name]]
            table = Table(meta, colWidths=[120, 360]); table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#d9edf7"))])); story += [table, Spacer(1, 14), Paragraph("Estimate Summary", styles["Heading2"])]
            data = [["Measure", "Hours", "Fees"], ["Customer Investment", format_hours(summary["investment_hours"]), f"{summary['fees']:,.2f}"], ["Plan Hours Not Billable", format_hours(summary["non_billable_hours"]), "—"], ["Total Internal Effort", format_hours(summary["total_internal_hours"]), "—"], ["Range Low", format_hours(summary["low_hours"]), f"{summary['low_fees']:,.2f}"], ["Range High", format_hours(summary["high_hours"]), f"{summary['high_fees']:,.2f}"]]
            table = Table(data, colWidths=[220, 100, 140]); table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0089a8")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)])); story += [table, Spacer(1, 14), Paragraph("Phase Summary", styles["Heading2"])]
            pdata = [["Phase", "Investment Hours", "Not Billable"]] + [[phase, format_hours(value["investment"]), format_hours(value["non_billable"])] for phase, value in summary["phase_totals"].items()]
            table = Table(pdata, colWidths=[240, 120, 120]); table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey)])); story.append(table)

        doc.build(story)
        buf.seek(0)
        record(db, event_type="PDF_GENERATED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id)
        db.commit()
        filename = f"{'CIP-' if product == PRODUCT_CIP else ''}Estimate-{rev.estimate.estimate_number}-Rev-{rev.revision_no}.pdf"
        return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def register_precision_startup(app):
    @app.on_event("startup")
    def upgrade_editable_calculation_versions():
        # Best-effort migration of editable revisions only. Locked commercial history remains pinned.
        db = SessionLocal()
        try:
            ids = [row.id for row in db.query(EstimateRevision).filter(EstimateRevision.status.in_(["DRAFT", "REVIEW"])).all()]
            for rid in ids:
                try:
                    with db.begin_nested():
                        rev = db.get(EstimateRevision, rid)
                        if revision_product(db, rev) == PRODUCT_CIP:
                            cip_recalculate(db, rev)
                        else:
                            mep_recalculate(db, rev)
                except Exception:
                    continue
            db.commit()
        finally:
            db.close()

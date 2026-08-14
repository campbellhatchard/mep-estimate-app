import csv
import io

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from .cip_domain import _cip_input, revision_product
from .cip_models import PRODUCT_MEP
from .database import get_db
from .models import ConfigurationVersion, ScheduleTask
from .services.audit import record
from .services.cip_calculation import CIPConfig, calculation as cip_calculation
from .services.cip_schedule import generate_cip_schedule


def register_export_routes(app, core, mep_pdf, mep_jira):
    @app.get("/estimate/{rid}/pdf")
    def pdf_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP: return mep_pdf(rid, request, db)
        user = core.current_user(request, db); _, summary, _, _ = cip_calculation(db, rev); inp = _cip_input(db, rid)
        cfg = CIPConfig(db, rev.config_version_id); release = cfg.item_by_key("CIP Release", inp.release_key)
        buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36); styles = getSampleStyleSheet()
        story = [Paragraph("Cloud Inventory Platform — Services Estimate", styles["Title"]), Spacer(1, 12)]
        meta = [["Customer", rev.customer], ["Estimate", f"{rev.estimate.estimate_number} Rev {rev.revision_no}"], ["Opportunity", rev.opportunity_number], ["Proposal Date", str(rev.proposal_date or "")], ["Project Type", inp.project_type], ["Deployed Over", inp.deployed_over], ["CIP Release", release.label if release else inp.release_key], ["Configuration", db.get(ConfigurationVersion, rev.config_version_id).name]]
        t = Table(meta, colWidths=[120, 360]); t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#d9edf7"))])); story += [t, Spacer(1, 14), Paragraph("Estimate Summary", styles["Heading2"])]
        data = [["Measure", "Hours", "Fees"], ["Customer Investment", f"{summary['investment_hours']:.0f}", f"{summary['fees']:,.2f}"], ["Plan Hours Not Billable", f"{summary['non_billable_hours']:.0f}", "—"], ["Total Internal Effort", f"{summary['total_internal_hours']:.0f}", "—"], ["Range Low", f"{summary['low_hours']:.0f}", f"{summary['low_fees']:,.2f}"], ["Range High", f"{summary['high_hours']:.0f}", f"{summary['high_fees']:,.2f}"]]
        t = Table(data, colWidths=[220, 100, 140]); t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0089a8")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)])); story += [t, Spacer(1, 14), Paragraph("Phase Summary", styles["Heading2"])]
        pdata = [["Phase", "Investment Hours", "Not Billable"]] + [[p, f"{v['investment']:.0f}", f"{v['non_billable']:.0f}"] for p, v in summary["phase_totals"].items()]
        pt = Table(pdata, colWidths=[240, 120, 120]); pt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .25, colors.grey)])); story.append(pt); doc.build(story); buf.seek(0)
        record(db, event_type="PDF_GENERATED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id); db.commit()
        return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="CIP-Estimate-{rev.estimate.estimate_number}-Rev-{rev.revision_no}.pdf"'})

    @app.get("/estimate/{rid}/jira.csv")
    def jira_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP: return mep_jira(rid, request, db)
        user = core.current_user(request, db); tasks = db.query(ScheduleTask).filter(ScheduleTask.revision_id == rev.id).order_by(ScheduleTask.sort_order).all()
        if not tasks: tasks = generate_cip_schedule(db, rev, replace=True); db.commit()
        headers = ["Issue Type","Issue Type ID","Summary","Description","Reporter","Original estimate (in hours)","Remaining Estimate","Outward issue link (Blocks) Issue Summary","Outward issue link (Blocks) Issue Type ID","Outward issue link (Blocks) Issue Summary 31","Outward issue link (Blocks) Issue Type ID 31","Outward issue link (Blocks) Issue Summary 32","Outward issue link (Blocks) Issue Type ID 32","Outward issue link (Blocks) Issue Summary 33","Outward issue link (Blocks) Issue Type ID 33","Outward issue link (Blocks) Issue Summary 34","Outward issue link (Blocks) Issue Type ID 34","Outward issue link (Blocks) Issue Summary 35","Outward issue link (Blocks) Issue Type ID 35","Outward issue link (Discovery - Connected) Issue Summary","Outward issue link (Discovery - Connected) Issue Type ID","Outward issue link (Relates) Issue Type Summary","Outward issue link (Relates) Issue Type ID","Outward issue link (Relates) Issue Type Summary 57","Outward issue link (Relates) Issue Type ID 57","Parent","Epic Name"]
        out = io.StringIO(); writer = csv.writer(out); writer.writerow(headers); issue_id = 1
        for phase in ["Plan", "Design", "Build", "Test", "Go Live"]:
            row = [""] * 27; row[0], row[1], row[2], row[26] = "Epic", issue_id, phase, phase; writer.writerow(row); epic_id = issue_id; issue_id += 1
            for task in [x for x in tasks if x.phase == phase and x.task != phase and x.billable_hours_budgeted > 0]:
                remaining = max(0, float(task.billable_hours_budgeted or 0) + float(task.change_order_hours or 0) - float(task.hours_used or 0)); row = [""] * 27
                row[0], row[1], row[2] = "Story", issue_id, task.task.replace("Not Included - ", ""); row[3] = task.description or task.purpose; row[5] = task.billable_hours_budgeted; row[6] = remaining; row[25], row[26] = epic_id, phase; writer.writerow(row); issue_id += 1
        record(db, event_type="JIRA_CSV_EXPORTED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id); db.commit()
        return StreamingResponse(io.BytesIO(out.getvalue().encode()), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="CIP-Estimate-{rev.estimate.estimate_number}-Jira.csv"'})

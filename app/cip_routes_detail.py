from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .cip_domain import _float, _int, revision_product
from .cip_models import CIPNonBillableAllocation, CIPScopeItem, PRODUCT_CIP, PRODUCT_MEP
from .database import get_db
from .models import CalculationAdjustment
from .services.audit import record
from .services.cip_calculation import calculation as cip_calculation, recalculate_and_store as cip_recalculate_and_store


def register_detail_routes(app, core, mep_detail_get, mep_detail_post, mep_calc_get, mep_calc_post):
    @app.get("/estimate/{rid}/detail", response_class=HTMLResponse)
    def detail_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP: return mep_detail_get(rid, request, db)
        user = core.current_user(request, db); _, summary, details, detail_summary = cip_calculation(db, rev)
        scope = {f"{row.category}:{row.catalog_key}": row for row in db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rev.id).all()}
        sections = []
        for name in ["Desktop Applications", "Custom Desktop Applications", "Mobile Applications", "Custom Mobile Applications", "Reporting Development", "Labels", "Baseline Integrations", "Custom Boomi Integrations", "RESTful Interfaces"]:
            rows = [x for x in details if x.section == name]
            rows = [x for x in rows if x.base_hours or x.added_hours or x.testing_adjustment or (x.definition.strip() and not (x.config_type == "No Config" and x.section in ("Custom Desktop Applications", "Custom Mobile Applications", "Reporting Development") and not (scope.get(x.key) and scope[x.key].description.strip())))]
            sections.append((name, rows, detail_summary.get(name, {})))
        return core.templates.TemplateResponse("cip_detail.html", {"request": request, "user": user, "rev": rev, "estimate": rev.estimate, "sections": sections, "scope": scope, "summary": summary, "readonly": rev.status in ("APPROVED", "FINAL", "SUPERSEDED"), "product_type": PRODUCT_CIP})

    @app.post("/estimate/{rid}/detail")
    async def detail_save_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP: return await mep_detail_post(rid, request, db)
        user = core.current_user(request, db); core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
        if rev.status in ("APPROVED", "FINAL", "SUPERSEDED"): raise HTTPException(409, "Revision is locked")
        form = await request.form(); count = _int(form, "line_count", 0)
        for idx in range(count):
            row = db.get(CIPScopeItem, _int(form, f"scope_id_{idx}", 0))
            if not row or row.revision_id != rev.id: continue
            added = _float(form, f"added_{idx}", row.added_hours); adj_notes = str(form.get(f"adjustment_notes_{idx}", row.adjustment_notes or "")).strip()
            test_adjust = _float(form, f"test_adjust_{idx}", row.testing_adjustment); test_notes = str(form.get(f"test_notes_{idx}", row.testing_notes or "")).strip()
            desc = str(form.get(f"description_{idx}", row.description or "")); app_count = _int(form, f"app_count_{idx}", row.app_count)
            integration_added = _float(form, f"integration_added_{idx}", row.integration_added_hours)
            if (added != 0 or integration_added != 0) and not adj_notes: raise HTTPException(400, f"Adjustment notes are required for {row.label}.")
            if test_adjust != 0 and not test_notes: raise HTTPException(400, f"Testing adjustment notes are required for {row.label}.")
            old = (row.added_hours, row.adjustment_notes, row.testing_adjustment, row.testing_notes, row.description, row.app_count, row.integration_added_hours)
            new = (added, adj_notes, test_adjust, test_notes, desc, app_count, integration_added)
            if old != new:
                record(db, event_type="CIP_DETAIL_ADJUSTED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id, field_name=f"{row.category}:{row.label}", old_value=str(old), new_value=str(new), reason=test_notes or adj_notes or None)
                row.added_hours, row.adjustment_notes, row.testing_adjustment, row.testing_notes, row.description = added, adj_notes, test_adjust, test_notes, desc
                row.app_count, row.integration_added_hours = max(0, app_count), integration_added
        rev.schedule_needs_refresh = True; cip_recalculate_and_store(db, rev); db.commit(); return RedirectResponse(f"/estimate/{rid}/detail", 303)

    @app.get("/estimate/{rid}/calculations", response_class=HTMLResponse)
    def calculations_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP: return mep_calc_get(rid, request, db)
        user = core.current_user(request, db); lines, summary, _, _ = cip_calculation(db, rev)
        phases = [(phase, [x for x in lines if x.phase == phase], summary["phase_totals"][phase]) for phase in ["Plan", "Design", "Build", "Test", "Go Live"]]
        return core.templates.TemplateResponse("cip_calculations.html", {"request": request, "user": user, "rev": rev, "estimate": rev.estimate, "phases": phases, "summary": summary, "readonly": rev.status in ("APPROVED", "FINAL", "SUPERSEDED"), "product_type": PRODUCT_CIP})

    @app.post("/estimate/{rid}/calculations")
    async def calculations_save_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP: return await mep_calc_post(rid, request, db)
        user = core.current_user(request, db); core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
        if rev.status in ("APPROVED", "FINAL", "SUPERSEDED"): raise HTTPException(409, "Revision is locked")
        form = await request.form(); count = _int(form, "line_count", 0)
        adjustments = {x.line_key: x for x in db.query(CalculationAdjustment).filter(CalculationAdjustment.revision_id == rev.id).all()}
        allocations = {x.line_key: x for x in db.query(CIPNonBillableAllocation).filter(CIPNonBillableAllocation.revision_id == rev.id).all()}
        for idx in range(count):
            key = str(form.get(f"line_key_{idx}", "")); phase = str(form.get(f"phase_{idx}", ""))
            if not key: continue
            adjust = _float(form, f"adjust_{idx}", 0); notes = str(form.get(f"notes_{idx}", "")).strip()
            if adjust != 0 and not notes: raise HTTPException(400, f"Adjustment notes are required for {key}.")
            row = adjustments.get(key)
            if not row and (adjust != 0 or notes): row = CalculationAdjustment(revision_id=rev.id, line_key=key); db.add(row); adjustments[key] = row
            if row and (row.adjust_hours != adjust or row.notes != notes):
                record(db, event_type="CALCULATION_ADJUSTED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id, field_name=key, old_value=f"{row.adjust_hours}|{row.notes}", new_value=f"{adjust}|{notes}", reason=notes or None); row.adjust_hours, row.notes = adjust, notes
            nb_hours = _float(form, f"nonbillable_{idx}", 0) if phase == "Plan" else 0; nb_notes = str(form.get(f"nonbillable_notes_{idx}", "")).strip() if phase == "Plan" else ""
            if nb_hours < 0: raise HTTPException(400, "Plan Hours Not Billable cannot be negative.")
            if nb_hours != 0 and not nb_notes: raise HTTPException(400, f"Non-billable notes are required for {key}.")
            alloc = allocations.get(key)
            if not alloc and (nb_hours != 0 or nb_notes): alloc = CIPNonBillableAllocation(revision_id=rev.id, line_key=key); db.add(alloc); allocations[key] = alloc
            if alloc and (alloc.hours != nb_hours or alloc.notes != nb_notes):
                record(db, event_type="CIP_NONBILLABLE_CHANGED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id, field_name=key, old_value=f"{alloc.hours}|{alloc.notes}", new_value=f"{nb_hours}|{nb_notes}", reason=nb_notes or None); alloc.hours, alloc.notes = nb_hours, nb_notes
        rev.schedule_needs_refresh = True; cip_recalculate_and_store(db, rev); db.commit(); return RedirectResponse(f"/estimate/{rid}/calculations", 303)

from datetime import date

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .cip_domain import (
    _bool, _cip_context, _cip_input, _ensure_dynamic_scope, _float, _int, _update_cip_field,
    revision_product, sync_cip_catalog, validate_cip,
)
from .cip_models import CIPScopeItem, PRODUCT_MEP
from .cip_revision import copy_cip_revision
from .database import get_db
from .services.audit import record
from .services.cip_calculation import recalculate_and_store as cip_recalculate_and_store


def register_estimate_routes(app, core, mep_estimate_get, mep_estimate_post, mep_new_revision):
    @app.get("/estimate/{rid}", response_class=HTMLResponse)
    def estimate_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP:
            return mep_estimate_get(rid, request, db)
        user = core.current_user(request, db)
        ctx = _cip_context(db, rev); ctx.update({"request": request, "user": user})
        return core.templates.TemplateResponse("cip_estimate.html", ctx)

    @app.post("/estimate/{rid}")
    async def estimate_save_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP:
            return await mep_estimate_post(rid, request, db)
        user = core.current_user(request, db); core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
        if rev.status in ("APPROVED", "FINAL", "SUPERSEDED"):
            raise HTTPException(409, "Approved/final revisions are locked")
        inp = _cip_input(db, rid); form = await request.form(); old_release = inp.release_key
        for field in ("customer", "customer_type", "opportunity_number", "currency", "entity"):
            core.update_field(db, rev, user, field, str(form.get(field, getattr(rev, field))))
        core.update_field(db, rev, user, "billing_rate", _float(form, "billing_rate", rev.billing_rate))
        if form.get("proposal_date"):
            core.update_field(db, rev, user, "proposal_date", date.fromisoformat(str(form["proposal_date"])))
        for field in ["release_key", "deployed_over", "project_type", "epp_install", "user_count", "go_live_type", "security_method"]:
            _update_cip_field(db, rev, inp, user, field, str(form.get(field, getattr(inp, field))))
        for field in ["label_sites", "label_count", "custom_boomi_count", "rest_interface_count", "testing_cycles", "go_live_sites", "uat_sites"]:
            _update_cip_field(db, rev, inp, user, field, _int(form, field, getattr(inp, field)))
        _update_cip_field(db, rev, inp, user, "base_test_pct", _float(form, "base_test_pct", inp.base_test_pct))
        percent_display = str(form.get("range_values_are_percent", "")) == "1"
        for field in ["low_factor", "high_factor"]:
            default_value = getattr(inp, field) * 100 if percent_display else getattr(inp, field)
            value = _float(form, field, default_value)
            if percent_display:
                value /= 100.0
            _update_cip_field(db, rev, inp, user, field, value)
        for field in ["gateway", "labels_required", "custom_boomi_required", "rest_required", "consultant_access_setup", "onboarding", "pacejet", "write_test_scripts", "end_user_documentation", "end_user_training", "cip_desktop_dev_training", "mobile_dev_training", "test_ihu", "test_lot_serial", "test_food_pharma", "test_location_dimension", "test_setup_customer_data", "test_monitored_session"]:
            _update_cip_field(db, rev, inp, user, field, _bool(form, field))
        for shared, value in [
            ("project_type", inp.project_type), ("erp", inp.deployed_over), ("epp_install", inp.epp_install),
            ("label_sites", inp.label_sites), ("labels_required", inp.labels_required), ("label_count", inp.label_count),
            ("consultant_access_setup", inp.consultant_access_setup), ("onboarding", inp.onboarding), ("user_count", inp.user_count),
            ("test_cycles", inp.testing_cycles), ("go_live_sites", inp.go_live_sites), ("go_live_type", inp.go_live_type),
            ("uat_sites", inp.uat_sites), ("base_test_pct", inp.base_test_pct), ("security_method", inp.security_method),
            ("pacejet", inp.pacejet), ("write_test_scripts", inp.write_test_scripts), ("end_user_documentation", inp.end_user_documentation),
            ("end_user_training", inp.end_user_training), ("gateway", inp.gateway),
        ]:
            if getattr(rev, shared) != value: setattr(rev, shared, value)
        if old_release != inp.release_key:
            sync_cip_catalog(db, rev, inp.release_key, force=True)
        _ensure_dynamic_scope(db, rev, inp)
        for row in db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rev.id).all():
            selected, description = form.get(f"scope_{row.id}"), form.get(f"desc_{row.id}")
            if selected is not None and str(selected) != row.config_type:
                record(db, event_type="ESTIMATE_FIELD_CHANGED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id,
                    field_name=f"CIP_SCOPE:{row.category}:{row.label}", old_value=row.config_type, new_value=str(selected)); row.config_type = str(selected)
            if description is not None and str(description) != row.description:
                record(db, event_type="ESTIMATE_FIELD_CHANGED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id,
                    field_name=f"CIP_SCOPE_DESC:{row.category}:{row.label}", old_value=row.description, new_value=str(description)); row.description = str(description)
        validate_cip(db, rev, inp); rev.schedule_needs_refresh = True; cip_recalculate_and_store(db, rev); db.commit()
        return RedirectResponse(f"/estimate/{rid}", 303)

    @app.post("/estimate/{rid}/new-revision")
    def new_revision_dispatch(rid: int, request: Request, rebase: bool = False, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP:
            return mep_new_revision(rid, request, rebase, db)
        user = core.current_user(request, db); core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
        new_rev = copy_cip_revision(db, core, rev, user, rebase)
        return RedirectResponse(f"/estimate/{new_rev.id}", 303)

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..cip_domain import revision_product
from ..cip_models import CIPRevisionInput, PRODUCT_CIP
from ..models import EstimateRevision, User
from ..sow_models import SOW
from .. import sow_routes, sow_service
from .core import cip_go_live_support_hours, cip_scope_lists

def _cip_sow_context(db: Session, request: Request, core, sow: SOW, user) -> dict:
    rev = db.get(EstimateRevision, sow.estimate_revision_id)
    if not rev:
        raise HTTPException(404, "Estimate revision not found")
    inp = db.get(CIPRevisionInput, rev.id)
    if not inp:
        raise HTTPException(404, "CIP estimate inputs not found")
    support_hours = cip_go_live_support_hours(db, rev)
    allocated = sum(float(x.allocated_hours or 0) for x in sow.hypercare_locations)
    history = (
        db.query(SOW)
        .filter(SOW.estimate_revision_id == rev.id)
        .order_by(desc(SOW.sow_revision_no))
        .all()
    )
    users = {u.id: u.username for u in db.query(User).all()}
    return {
        "request": request,
        "user": user,
        "sow": sow,
        "rev": rev,
        "estimate": rev.estimate,
        "inp": inp,
        "product_type": PRODUCT_CIP,
        "active_tab": "sow",
        "readonly": sow.status != "DRAFT",
        "history": history,
        "approvers": sow_routes._active_sow_approvers(db),
        "users": users,
        "agreement_types": sow_service.AGREEMENT_TYPES,
        "invoice_frequencies": sow_service.INVOICE_FREQUENCIES,
        "support_types": sow_service.SUPPORT_TYPES,
        "device_types": sow_service.DEVICE_TYPES,
        "go_live_support_hours": support_hours,
        "allocated_hours": allocated,
        "unallocated_hours": support_hours - allocated,
        "can_approve": (
            user.has_role("SOW_APPROVER")
            and sow.status == "PENDING_APPROVAL"
            and sow.approver_id == user.id
        ),
        "can_prepare": user.has_role(*sow_routes.PREP_ROLES),
        "is_standalone": inp.deployed_over == "Standalone",
        "is_jde": inp.deployed_over == "JD Edwards",
        "epp_included": inp.epp_install != "No",
        "rest_included": bool(inp.rest_required and inp.rest_interface_count > 0),
        "gateway_included": bool(inp.gateway),
        "scope": cip_scope_lists(db, rev),
    }


def _save_cip_sow(db: Session, sow: SOW, rev: EstimateRevision, user, form) -> None:
    fields = {
        "agreement_type": str(form.get("agreement_type", sow.agreement_type)).strip(),
        "invoice_frequency": str(form.get("invoice_frequency", sow.invoice_frequency)).strip(),
        "project_objective": str(form.get("project_objective", sow.project_objective)).strip(),
        "barcode_printer_count": sow_routes._as_int(
            form.get("barcode_printer_count", sow.barcode_printer_count)
        ),
        "erp_version": str(form.get("erp_version", sow.erp_version)).strip(),
        "erp_base_code_version": str(
            form.get("erp_base_code_version", sow.erp_base_code_version)
        ).strip(),
        "erp_tools_release": str(form.get("erp_tools_release", sow.erp_tools_release)).strip(),
        "erp_os_version": str(form.get("erp_os_version", sow.erp_os_version)).strip(),
        "erp_database_version": str(
            form.get("erp_database_version", sow.erp_database_version)
        ).strip(),
        "epp_product_version": str(
            form.get("epp_product_version", sow.epp_product_version)
        ).strip(),
        "print_methods": str(form.get("print_methods", sow.print_methods)).strip(),
        "erp_deployment_model": str(
            form.get("erp_deployment_model", sow.erp_deployment_model)
        ).strip(),
    }
    for field, value in fields.items():
        old = getattr(sow, field)
        sow_routes._audit_field(db, user, rev, sow, field, old, value)
        setattr(sow, field, value)
    # REST scope and product version are estimate/config controlled for Net New CIP.
    inp = db.get(CIPRevisionInput, rev.id)
    sow.rest_api_required = bool(inp and inp.rest_required)
    sow_routes._replace_child_rows(db, sow, form, user, rev)


def _product_for_sow(db: Session, sow: SOW) -> str:
    rev = db.get(EstimateRevision, sow.estimate_revision_id)
    if not rev:
        raise HTTPException(404, "Estimate revision not found")
    return revision_product(db, rev)

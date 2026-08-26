from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_domain import _take_route, revision_product
from .database import get_db
from .models import AuditEvent, ConfigurationVersion, EstimateRevision, User
from .services.audit import record


WORKING_STATUSES = ("DRAFT", "REVIEW")
LOCKED_STATUSES = ("APPROVED", "FINAL", "SUPERSEDED")


def _validate_mep_business_rules(core, db: Session, rev: EstimateRevision) -> None:
    """Workbook rules plus the controlled EPP On Prem -> Gateway dependency."""
    cfg = core.Config(db, rev.config_version_id)
    solution = cfg.json_by_label("Solution Type", rev.project_type)
    errors: list[str] = []
    epp_on_prem = rev.epp_install == "On Prem"

    if rev.high_availability and not bool(solution.get("ha_valid", False)):
        errors.append(f"MEP High Availability is not valid for {rev.project_type}.")
    # EPP On Prem is an explicit Gateway-required architecture.  Treat that as a
    # valid Gateway use case even when legacy Solution Type metadata did not mark
    # the project type as gateway_valid, otherwise the UI would be contradictory.
    if rev.gateway and not (bool(solution.get("gateway_valid", False)) or epp_on_prem):
        errors.append(f"MEP Gateway is not valid for {rev.project_type}.")
    if epp_on_prem and not rev.gateway:
        errors.append("Install MEP Gateway must be Yes when Install EPP is On Prem.")
    if rev.epp_integration != "None" and not rev.project_type.startswith("EPP"):
        errors.append("EPP Integration is valid only for an EPP project type.")
    if rev.epp_install != "No" and rev.label_sites < 1:
        errors.append("At least one label-printing site is required when EPP is installed.")
    if rev.epp_install == "No" and rev.label_sites > 0:
        errors.append("Label-printing site count must be zero when EPP is not installed.")
    if not rev.labels_required and rev.label_count > 0:
        errors.append("Label Count is greater than zero while Labels Required is No.")
    if (not rev.iot_required and rev.iot_count > 0) or (rev.iot_required and rev.iot_count == 0):
        errors.append("Conveyor / scale interface selection and Service Definition Count are inconsistent.")
    if rev.iot_count > 10:
        errors.append("Conveyor / scale Service Definition Count must be between 1 and 10.")
    if not rev.erp_integration_required and rev.erp_integration_count > 0:
        errors.append("ERP Integration Count is greater than zero while ERP Integration Required is No.")
    if (not rev.data_rep_required and rev.data_rep_count > 0) or (rev.data_rep_required and rev.data_rep_count == 0):
        errors.append("Data Replication selection and Data Replication Session Count are inconsistent.")
    if rev.data_rep_count > 20:
        errors.append("Data Replication Session Count must be between 1 and 20.")
    selected_standard = sum(1 for row in rev.applications if row.config_type != "No Config")
    selected_custom = sum(1 for row in rev.custom_apps if row.description and row.complexity != "No Config")
    if (selected_standard + selected_custom) > 0 and rev.go_live_type == "None":
        errors.append("A Go Live Type is required when applications or packages are included.")
    if rev.go_live_type != "None" and rev.go_live_sites < 1:
        errors.append("Number of Go Live Sites must be at least 1 when a Go Live Type is selected.")
    for row in rev.custom_apps:
        if not row.description.strip() and row.complexity != "No Config":
            errors.append(f"Custom Application {row.sort_order + 1} has effort selected but no description.")
    if errors:
        raise HTTPException(400, " ".join(errors))


def install_estimate_business_rule_controls(core) -> None:
    """Install the EPP dependency before product routes capture validation callables."""
    core.validate_estimate_business_rules = lambda db, rev: _validate_mep_business_rules(core, db, rev)

    # CIP already enforces EPP -> positive site count.  Extend its existing
    # validator with the same On Prem -> Gateway dependency and update both the
    # module attribute and the route module's imported binding.
    from . import cip_domain, cip_routes_estimate

    original_cip_validate = cip_domain.validate_cip

    def validate_cip_with_gateway(db, rev, inp):
        original_cip_validate(db, rev, inp)
        if inp.epp_install == "On Prem" and not inp.gateway:
            raise HTTPException(400, "Gateway must be Yes when EPP Install is On Prem.")

    cip_domain.validate_cip = validate_cip_with_gateway
    cip_routes_estimate.validate_cip = validate_cip_with_gateway


def _working_revision(db: Session, estimate_id: int, *, exclude_id: int | None = None):
    query = db.query(EstimateRevision).filter(
        EstimateRevision.estimate_id == estimate_id,
        EstimateRevision.status.in_(WORKING_STATUSES),
    )
    if exclude_id is not None:
        query = query.filter(EstimateRevision.id != exclude_id)
    return query.order_by(desc(EstimateRevision.revision_no)).first()


def register_revision_rationale_controls(app, core) -> None:
    """Require and display user-entered rationale without mutating historical revisions."""
    previous_history = _take_route(app, "/estimate/{rid}/revisions", "GET")
    previous_new_revision = _take_route(app, "/estimate/{rid}/new-revision", "POST")
    if previous_history is None or previous_new_revision is None:
        raise RuntimeError("Revision history routes must be registered before rationale controls.")

    @app.get("/estimate/{rid}/revisions", response_class=HTMLResponse)
    def revision_history_with_reason(
        rid: int, request: Request, db: Session = Depends(get_db)
    ):
        user = core.current_user(request, db)
        rev = core.revision_or_404(db, rid)
        revisions = (
            db.query(EstimateRevision)
            .filter(EstimateRevision.estimate_id == rev.estimate_id)
            .order_by(desc(EstimateRevision.revision_no))
            .all()
        )
        users = {row.id: row.username for row in db.query(User).all()}
        config_ids = {row.config_version_id for row in revisions}
        configs = {
            row.id: row.name
            for row in db.query(ConfigurationVersion)
            .filter(ConfigurationVersion.id.in_(config_ids))
            .all()
        } if config_ids else {}

        approval_events = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.estimate_id == rev.estimate_id,
                AuditEvent.event_type == "ESTIMATE_APPROVED",
            )
            .order_by(desc(AuditEvent.created_at))
            .all()
        )
        approved_by_revision: dict[int, AuditEvent] = {}
        for event in approval_events:
            approved_by_revision.setdefault(event.revision_id, event)

        rationale_events = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.estimate_id == rev.estimate_id,
                AuditEvent.event_type == "REVISION_RATIONALE",
            )
            .order_by(desc(AuditEvent.created_at))
            .all()
        )
        rationale_by_revision: dict[int, AuditEvent] = {}
        for event in rationale_events:
            rationale_by_revision.setdefault(event.revision_id, event)

        current_approved = next(
            (row for row in revisions if row.status in ("APPROVED", "FINAL")), None
        )
        working = next((row for row in revisions if row.status in WORKING_STATUSES), None)
        rows = []
        for item in revisions:
            approval = approved_by_revision.get(item.id)
            rationale = rationale_by_revision.get(item.id)
            rows.append(
                {
                    "rev": item,
                    "config_name": configs.get(
                        item.config_version_id, f"Config {item.config_version_id}"
                    ),
                    "created_by": users.get(item.created_by, "System"),
                    "approved_at": approval.created_at if approval else None,
                    "approved_by": users.get(approval.user_id, "System") if approval else "",
                    "revision_reason": rationale.reason if rationale else "",
                    "revision_kind": rationale.old_value if rationale else "",
                    "is_current_approved": bool(
                        current_approved and current_approved.id == item.id
                    ),
                }
            )
        return core.templates.TemplateResponse(
            "revision_history.html",
            {
                "request": request,
                "user": user,
                "rev": rev,
                "estimate": rev.estimate,
                "rows": rows,
                "working": working,
                "current_approved": current_approved,
                "product_type": revision_product(db, rev),
            },
        )

    @app.post("/estimate/{rid}/new-revision")
    async def new_revision_with_reason(
        rid: int,
        request: Request,
        rebase: bool = False,
        db: Session = Depends(get_db),
    ):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
        src = core.revision_or_404(db, rid)
        if src.status not in LOCKED_STATUSES:
            raise HTTPException(
                409,
                "Create a new revision only from an Approved, Final, or Superseded revision.",
            )

        working = _working_revision(db, src.estimate_id, exclude_id=src.id)
        if working:
            return RedirectResponse(f"/estimate/{working.id}", 303)

        form = await request.form()
        reason = str(form.get("revision_reason", "")).strip()
        if not reason:
            status_code = 400 if "revision_reason" in form else 200
            return core.templates.TemplateResponse(
                "revision_reason.html",
                {
                    "request": request,
                    "user": user,
                    "rev": src,
                    "estimate": src.estimate,
                    "rebase": rebase,
                    "error": (
                        "Revision Notes are required before a new revision can be created."
                        if status_code == 400
                        else None
                    ),
                },
                status_code=status_code,
            )

        response = previous_new_revision(rid, request, rebase, db)
        location = response.headers.get("location", "")
        try:
            new_rid = int(location.rstrip("/").rsplit("/", 1)[-1])
        except (TypeError, ValueError):
            return response
        new_rev = db.get(EstimateRevision, new_rid)
        if new_rev and new_rev.estimate_id == src.estimate_id and new_rev.id != src.id:
            record(
                db,
                event_type="REVISION_RATIONALE",
                user_id=user.id,
                estimate_id=new_rev.estimate_id,
                revision_id=new_rev.id,
                config_version_id=new_rev.config_version_id,
                field_name="REVISION_REASON",
                old_value="REBASE" if rebase else "REVISION",
                new_value=f"Rev {new_rev.revision_no}",
                reason=reason,
            )
            db.commit()
        return response

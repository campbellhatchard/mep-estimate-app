from __future__ import annotations

import re
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .database import get_db
from .models import User, UserRole, ROLE_ORDER, ScheduleTask
from .auth import current_user, require_role, normalize_username, hash_password
from .services.audit import record

ROLE_LABELS = {
    "ADMIN": "Administrator",
    "ESTIMATOR": "Estimator",
    "REVIEWER": "Reviewer",
    "APPROVER": "Approver",
    "READ_ONLY": "Read Only",
}

# User-facing terminology corrections. Internal keys and legacy stored values remain
# stable wherever changing them could alter calculation behavior or historical parity.
TERM_MAP = {
    "Base Line Applications": "Baseline Applications",
    "Install_Base": "Install Base",
    "Net_New": "Net New",
    "Oracle Net Suite": "Oracle NetSuite",
    "OKTA": "Okta",
    "Add 20 %": "Add 20%",
    "On Hold- Customer": "On Hold - Customer",
    "On Hold- CI": "On Hold - CI",
    "SAP 6": "SAP ECC 6.0",
    "SAP HANA / HANA 22": "SAP S/4HANA 2022",
    "Stand Alone": "Standalone",
    "US Dollars": "US Dollar",
    "Goods Issue to Cost Cent": "Goods Issue to Cost Center",
    "Goods Issue To Plant Maint": "Goods Issue to Plant Maintenance",
    "Goors Receipt to Production": "Goods Receipt to Production",
    "Inventory Iquiry": "Inventory Inquiry",
    "Purchase ORder Receipt": "Purchase Order Receipt",
    "Qual/block Unrestricted Xfer": "Quality/Blocked to Unrestricted Transfer",
    "Account Aliasis Isue": "Account Alias Issue",
    "Miscelanious Issue": "Miscellaneous Issue",
    "Miscelanious Receipt": "Miscellaneous Receipt",
    "Miscelanious Transaction": "Miscellaneous Transaction",
    "Project Alian Receipt": "Project Alias Receipt",
    "Project Mover Order Return": "Project Move Order Return",
    "Reeturn Receipt": "Return Receipt",
    "Sub Inventory Transfer": "Subinventory Transfer",
    "Invenotry Issue": "Inventory Issue",
    "inventory Adjustment Positive": "Inventory Adjustment Positive",
    "P O Receipt Label Option": "PO Receipt Label Option",
    "W O Comp Label Option": "WO Completion Label Option",
    "Work Order Tiem Entry": "Work Order Time Entry",
    "Fixed Aset Inquiry": "Fixed Asset Inquiry",
    "Inventory Recalss": "Inventory Reclassification",
    "Pick Conifirmation": "Pick Confirmation",
    "AsjuInventory Adjustment NEGstment Negative": "Inventory Adjustment Negative",
    "Inventlory Inquiry": "Inventory Inquiry",
    "Work ORder Issue/Pick": "Work Order Issue/Pick",
}

TEXT_REPLACEMENTS = [
    ("Accesss", "Access"),
    ("devlopment", "development"),
    ("online trading", "online training"),
    ("requried", "required"),
    ("they ar a great", "they are a great"),
    ("phsyically", "physically"),
    ("theMEP", "the MEP"),
    ("MEPand", "MEP and"),
    ("baselie", "baseline"),
    ("avaialble", "available"),
    ("tset scripts", "test scripts"),
    ("reporrting", "reporting"),
    ("intial", "initial"),
    ("envionment", "environment"),
    ("anad customer", "and customer"),
    ("suporting", "supporting"),
    ("Post-Mortum", "Post-Mortem"),
    ("restrospective", "retrospective"),
    ("as associate as possible", "as accurate as possible"),
    ("successful work.", "successful workshop."),
    ("Pacejet", "PaceJet"),
    ("Pace Jet", "PaceJet"),
    ("CloudOps", "Cloud Ops"),
    ("Presales", "PreSales"),
    ("Go-live", "Go-Live"),
    ("Go Live", "Go-Live"),
    ("Sign Off", "Sign-Off"),
]


def ci_term(value):
    if value is None:
        return ""
    text = str(value)
    return TERM_MAP.get(text, text)


def ci_text(value):
    if value is None:
        return ""
    text = TERM_MAP.get(str(value), str(value))
    for old, new in TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    text = re.sub(r"\bIOT\b", "IoT", text)
    text = re.sub(r"\bJIRA\b", "Jira", text)
    return text


def configure_templates(templates):
    templates.env.filters["ci_term"] = ci_term
    templates.env.filters["ci_text"] = ci_text
    templates.env.globals["ROLE_OPTIONS"] = ROLE_ORDER
    templates.env.globals["ROLE_LABELS"] = ROLE_LABELS


def _ordered_roles(form) -> list[str]:
    selected = {str(x) for x in form.getlist("roles")}
    return [role for role in ROLE_ORDER if role in selected]


def _set_roles(user: User, roles: list[str]):
    user.roles.clear()
    for role in roles:
        user.roles.append(UserRole(role=role))
    # Retain one role in the legacy field for backward compatibility with old exports/code.
    user.role = roles[0] if roles else "READ_ONLY"


def _other_active_admin_count(db: Session, user_id: int) -> int:
    return (
        db.query(User)
        .join(UserRole, UserRole.user_id == User.id)
        .filter(User.id != user_id, User.active.is_(True), UserRole.role == "ADMIN")
        .count()
    )


def register_routes(app):
    router = APIRouter()

    @router.post("/admin/users/create")
    async def create_user(request: Request, db: Session = Depends(get_db)):
        actor = current_user(request, db)
        require_role(actor, "ADMIN")
        form = await request.form()
        username = str(form.get("username", "")).strip()
        email = str(form.get("email", "")).strip() or None
        password = str(form.get("password", ""))
        roles = _ordered_roles(form)
        active = str(form.get("active", "")).lower() in ("1", "true", "yes", "on")
        if not username:
            raise HTTPException(400, "Username is required")
        if len(password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        if not roles:
            raise HTTPException(400, "Select at least one role")
        norm = normalize_username(username)
        if db.query(User).filter(User.username_normalized == norm).first():
            raise HTTPException(409, "Username already exists ignoring case")
        target = User(
            username=username,
            username_normalized=norm,
            password_hash=hash_password(password),
            role=roles[0],
            email=email,
            active=active,
        )
        db.add(target)
        db.flush()
        _set_roles(target, roles)
        record(
            db,
            event_type="USER_CREATED",
            user_id=actor.id,
            field_name=f"USER:{target.username}",
            new_value=f"email={email or ''}; active={active}; roles={','.join(roles)}",
        )
        db.commit()
        return RedirectResponse("/admin/users", 303)

    @router.post("/admin/users/{uid}/update")
    async def update_user(uid: int, request: Request, db: Session = Depends(get_db)):
        actor = current_user(request, db)
        require_role(actor, "ADMIN")
        target = db.get(User, uid)
        if not target:
            raise HTTPException(404, "User not found")
        form = await request.form()
        email = str(form.get("email", "")).strip() or None
        roles = _ordered_roles(form)
        active = str(form.get("active", "")).lower() in ("1", "true", "yes", "on")
        password = str(form.get("password", ""))
        if not roles:
            raise HTTPException(400, "Select at least one role")
        removing_last_admin = target.has_role("ADMIN") and ("ADMIN" not in roles or not active)
        if removing_last_admin and _other_active_admin_count(db, target.id) == 0:
            raise HTTPException(409, "At least one active Administrator must remain")
        old = f"email={target.email or ''}; active={target.active}; roles={','.join(target.role_names)}"
        target.email = email
        target.active = active
        _set_roles(target, roles)
        if password:
            if len(password) < 8:
                raise HTTPException(400, "Password must be at least 8 characters")
            target.password_hash = hash_password(password)
        new = f"email={target.email or ''}; active={target.active}; roles={','.join(target.role_names)}"
        record(
            db,
            event_type="USER_UPDATED",
            user_id=actor.id,
            field_name=f"USER:{target.username}",
            old_value=old,
            new_value=new,
            reason="Password reset" if password else None,
        )
        db.commit()
        return RedirectResponse("/admin/users", 303)

    app.include_router(router)


def clean_schedule_tasks(tasks: list[ScheduleTask]):
    """Normalize approved spelling for generated schedule content without altering source formulas."""
    for task in tasks:
        task.task = ci_text(task.task)
        task.task_owner = "DC" if task.task_owner == "CD" else ci_text(task.task_owner)
        task.description = ci_text(task.description)
        task.purpose = ci_text(task.purpose)
    return tasks

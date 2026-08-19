from __future__ import annotations

import hashlib
import html
import io
import json
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph as RLParagraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_domain import _take_route, revision_product
from .cip_models import CIPRevisionInput, CIPScopeItem, PRODUCT_CIP, PRODUCT_MEP
from .database import SessionLocal, get_db
from .models import EstimateCustomApplication, EstimateApplication, EstimateRevision, User, UserRole
from .services.audit import record
from .services.calculation_v101 import calculation as mep_calculation
from .services.cip_calculation_v101 import calculation as cip_calculation
from .sow_models import (
    SOW, SOWDevice, SOWHypercareLocation, SOWTemplateVersion, SmallProjectSOWConfig,
)
from . import sow_routes, sow_service


SOW_TEMPLATE_MEP_SMALL_PROJECT = "MEP_SMALL_PROJECT"
SOW_TEMPLATE_CIP_SMALL_PROJECT = "CIP_SMALL_PROJECT"
SMALL_PROJECT_KEYS = {SOW_TEMPLATE_MEP_SMALL_PROJECT, SOW_TEMPLATE_CIP_SMALL_PROJECT}
TEMPLATE_DIR = Path(__file__).parent / "small_project_templates"
TEMPLATE_FILES = {
    PRODUCT_MEP: "MEP_Template_SmallProject_2026_08.docx",
    PRODUCT_CIP: "CIP_Template_SmallProject_2026_07.docx",
}
TEMPLATE_LABELS = {
    PRODUCT_MEP: "MEP Small Project SOW",
    PRODUCT_CIP: "CIP Small Project SOW",
}
AGREEMENT_TYPES = sow_service.AGREEMENT_TYPES
INVOICE_FREQUENCIES = sow_service.INVOICE_FREQUENCIES
SUPPORT_TYPES = sow_service.SUPPORT_TYPES
DEVICE_TYPES = sow_service.DEVICE_TYPES
PREP_ROLES = sow_routes.PREP_ROLES
EPP_DEPLOYMENT_MODELS = ("Cloud", "On-Premises")
MEP_INSTALL_MODES = ("", "Cloud", "On-Premises")
METHOD_OVERRIDE_OPTIONS = ("AUTO", "INCLUDE", "EXCLUDE")

METHODS = [
    ("PROJECT_PLANNING", "Project Planning Session"),
    ("KICKOFF", "Project Kickoff Meeting"),
    ("ADW", "Architecture Design Workshop (ADW)"),
    ("REQUIREMENTS", "Requirement Definition"),
    ("DEPLOYMENT", "Solution Application Deployment"),
    ("UNIT_TEST", "Unit Testing"),
    ("DEVICE_CONFIG", "Mobile Client Device Configuration"),
    ("KEY_USER_TRAINING", "Key User Training"),
    ("UAT", "Support User Acceptance Testing"),
    ("LOAD_TEST", "Limited Load Test"),
    ("GO_LIVE_PREP", "Prepare for Go Live"),
    ("HYPERCARE", "Hypercare"),
]

SAFE_REPLACEMENTS = {
    "Cloud Inventory® personal required": "Cloud Inventory® personnel required",
    "Where define in requirements": "Where defined in requirements",
    "Review any know Customer supplied": "Review any known Customer-supplied",
    "a variety of screen size.": "a variety of screen sizes.",
    "device make model": "device make and model",
    "supported sever operating system": "supported server operating system",
    "timeline..": "timeline.",
    "Cloud Invnetory": "Cloud Inventory",
    "integration from CPP to the ERP Solution": "integration from CIP to the ERP Solution",
    "Cloud Inventory Platform ((CIP))": "Cloud Inventory Platform (CIP)",
    "Cloud Inventory®\xa0": "Cloud Inventory® ",
    "Cloud Inventory ®": "Cloud Inventory®",
    "Cloud inventory®": "Cloud Inventory®",
    "aCIP administrator": "A CIP administrator",
    "United State Dollar (USD) currency": "U.S. dollars (USD)",
    "agreed up on terms": "agreed-upon terms",
    "Customer has identified requirements identified as custom.": "Customer has identified requirements that require custom development.",
    "time and material basis": "time-and-materials basis",
    "Actual hours and cost may vary.": "Actual hours and costs may vary.",
    "support is subject to a 4 hours per day minimum.": "support is subject to a four (4)-hour minimum per day.",
}

def _json_load(raw: str, default):
    try:
        value = json.loads(raw or "")
        return value if isinstance(value, type(default)) else default
    except Exception:
        return default

def _json_dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

def _product_template_key(product: str) -> str:
    return SOW_TEMPLATE_CIP_SMALL_PROJECT if product == PRODUCT_CIP else SOW_TEMPLATE_MEP_SMALL_PROJECT

def _product_for_sow(db: Session, sow: SOW) -> str:
    tmpl = db.get(SOWTemplateVersion, sow.template_version_id)
    if tmpl and tmpl.template_key == SOW_TEMPLATE_CIP_SMALL_PROJECT:
        return PRODUCT_CIP
    if tmpl and tmpl.template_key == SOW_TEMPLATE_MEP_SMALL_PROJECT:
        return PRODUCT_MEP
    rev = db.get(EstimateRevision, sow.estimate_revision_id)
    return revision_product(db, rev) if rev else PRODUCT_MEP

def is_small_project_sow(db: Session, sow: SOW) -> bool:
    tmpl = db.get(SOWTemplateVersion, sow.template_version_id)
    return bool(tmpl and tmpl.template_key in SMALL_PROJECT_KEYS)

def small_project_eligible(db: Session, rev: EstimateRevision) -> bool:
    return (
        rev.status in ("APPROVED", "FINAL", "SUPERSEDED")
        and rev.customer_type == "Install_Base"
        and rev.project_type == "Small Project"
        and revision_product(db, rev) in (PRODUCT_MEP, PRODUCT_CIP)
    )

def _active_template(db: Session, product: str) -> SOWTemplateVersion:
    key = _product_template_key(product)
    row = (
        db.query(SOWTemplateVersion)
        .filter(SOWTemplateVersion.template_key == key, SOWTemplateVersion.status == "ACTIVE")
        .order_by(desc(SOWTemplateVersion.version_no))
        .first()
    )
    if not row:
        raise ValueError(f"No active {TEMPLATE_LABELS[product]} template is available.")
    return row

def seed_small_project_templates(db: Session) -> None:
    admin = db.query(User).filter(User.username_normalized == "admin").first()
    if not admin:
        return
    changed = False
    for product in (PRODUCT_MEP, PRODUCT_CIP):
        key = _product_template_key(product)
        if db.query(SOWTemplateVersion).filter(SOWTemplateVersion.template_key == key).count():
            continue
        path = TEMPLATE_DIR / TEMPLATE_FILES[product]
        if not path.exists():
            continue
        content = path.read_bytes()
        row = SOWTemplateVersion(
            template_key=key,
            label=TEMPLATE_LABELS[product],
            product_type=product,
            customer_type="Install_Base",
            version_no=1,
            status="ACTIVE",
            filename=path.name,
            content=content,
            content_sha256=hashlib.sha256(content).hexdigest(),
            change_reason="Initial controlled Small Project SOW template supplied for existing implementations.",
            created_by=admin.id,
            activated_by=admin.id,
            activated_at=datetime.utcnow(),
        )
        db.add(row)
        db.flush()
        record(
            db, event_type="SOW_TEMPLATE_ACTIVATED", user_id=admin.id,
            field_name=f"SOW_TEMPLATE:{key}:1", new_value=path.name, reason=row.change_reason,
        )
        changed = True
    if changed:
        db.commit()

def _calc_lines(db: Session, rev: EstimateRevision):
    if revision_product(db, rev) == PRODUCT_CIP:
        lines, _, _, _ = cip_calculation(db, rev)
        return [(x.key, x.description, float(x.investment_hours or 0)) for x in lines]
    lines, _, _, _ = mep_calculation(db, rev)
    return [(x.key, x.description, float(x.extended_hours or 0)) for x in lines]

def _hours_map(db: Session, rev: EstimateRevision) -> dict[str, float]:
    return {key: hours for key, _, hours in _calc_lines(db, rev)}

def _any_hours(hours: dict[str, float], *keys_or_prefixes: str) -> bool:
    for needle in keys_or_prefixes:
        for key, value in hours.items():
            if value <= 0:
                continue
            if key == needle or key.startswith(needle):
                return True
    return False

def methodology_auto(db: Session, rev: EstimateRevision) -> dict[str, bool]:
    h = _hours_map(db, rev)
    return {
        "PROJECT_PLANNING": _any_hours(h, "PLAN_PREP", "PLAN_PM"),
        "KICKOFF": _any_hours(h, "PLAN_KICKOFF"),
        "ADW": _any_hours(h, "PLAN_ADW"),
        "REQUIREMENTS": _any_hours(h, "PLAN_ORIENTATION", "PLAN_GAP", "PLAN_BRD", "DESIGN_SOLUTION"),
        "DEPLOYMENT": _any_hours(h, "BUILD_"),
        "UNIT_TEST": _any_hours(h, "BUILD_UNIT_TEST"),
        "DEVICE_CONFIG": _any_hours(h, "BUILD_HANDHELD_SETUP", "BUILD_PRINTER_DEVICE"),
        "KEY_USER_TRAINING": _any_hours(h, "BUILD_WORKSHOP", "TEST_KEY_USER_TRAINING"),
        "UAT": _any_hours(h, "TEST_UAT"),
        "LOAD_TEST": _any_hours(h, "TEST_LOAD"),
        "GO_LIVE_PREP": _any_hours(h, "TEST_READINESS", "TEST_PROD_VALIDATION", "GO_LIVE_PREP"),
        "HYPERCARE": _any_hours(h, "GO_LIVE_SUPPORT", "GOLIVE_SUPPORT"),
    }

def _default_methodology() -> list[dict]:
    return [{"key": key, "title": title, "override": "AUTO"} for key, title in METHODS]

def _mep_default_deliverables(db: Session, rev: EstimateRevision) -> list[dict]:
    apps = [
        row.label for row in db.query(EstimateApplication)
        .filter(EstimateApplication.revision_id == rev.id, EstimateApplication.kind == "APPLICATION")
        .order_by(EstimateApplication.sort_order).all()
        if row.config_type != "No Config"
    ]
    customs = [
        row.description.strip() for row in db.query(EstimateCustomApplication)
        .filter(EstimateCustomApplication.revision_id == rev.id)
        .order_by(EstimateCustomApplication.sort_order).all()
        if row.description.strip() and row.complexity != "No Config"
    ]
    integration_details = []
    if rev.gateway: integration_details.append("Cloud Connect Gateway")
    if rev.erp_integration_required: integration_details.append(f"{rev.erp_integration_count} ERP service definition(s)")
    if rev.iot_required: integration_details.append(f"{rev.iot_count} IoT/interface service definition(s)")
    if rev.data_rep_required: integration_details.append(f"{rev.data_rep_count} data replication session(s)")
    rows = [
        {"key":"INSTALL","title":"MEP Installation / Platform Change","included":False,
         "description":"Install or revise the existing Mobile Enterprise Platform deployment as defined for this project.","details":""},
        {"key":"EPP","title":"Enterprise Printing Platform (EPP)","included":rev.epp_install != "No",
         "description":"Configure the Enterprise Printing Platform components included in this project.","details":""},
        {"key":"BASELINE","title":"Baseline Application Changes","included":bool(apps),
         "description":"Configure or modify the following existing/baseline applications.","details":"\n".join(apps)},
        {"key":"CUSTOM","title":"Develop and Deliver Custom Applications","included":bool(customs),
         "description":"Develop and configure the custom application scope defined for this project.","details":"\n".join(customs)},
        {"key":"LABELS","title":"Develop, Deploy and Configure Labels","included":bool(rev.labels_required or rev.label_count),
         "description":"Develop and configure labels defined by the approved project requirements.","details":f"{int(rev.label_count or 0)} label(s)" if rev.label_count else ""},
        {"key":"SECURITY","title":"Configure for User Security","included":rev.security_method != "None",
         "description":"Configure security-related components included in this project. Customer remains responsible for user and role administration unless expressly stated otherwise.","details":rev.security_method if rev.security_method != "None" else ""},
        {"key":"INTEGRATION","title":"Configure Integration and Connection Strings","included":bool(integration_details),
         "description":"Configure the integration, connection, and service-definition components included in this project.","details":"\n".join(integration_details)},
    ]
    return rows

def _cip_default_deliverables(db: Session, rev: EstimateRevision) -> list[dict]:
    inp = db.get(CIPRevisionInput, rev.id)
    scope = db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rev.id).order_by(CIPScopeItem.sort_order).all()
    selected = [x for x in scope if x.config_type != "No Config"]
    def items_matching(words):
        out=[]
        for x in selected:
            key=(x.category+" "+x.label+" "+x.description).casefold()
            if any(w in key for w in words):
                out.append(x.description.strip() or x.label)
        return out
    labels = items_matching(["label"])
    integrations = items_matching(["integration", "boomi", "rest"])
    custom = [x.description.strip() or x.label for x in selected if "custom" in x.category.casefold() or "custom" in x.label.casefold()]
    baseline = [x.description.strip() or x.label for x in selected
                if not any(w in (x.category+" "+x.label).casefold() for w in ("custom","label","integration","boomi","rest"))]
    security = inp.security_method if inp else rev.security_method
    epp = inp.epp_install if inp else rev.epp_install
    return [
        {"key":"INSTALL","title":"CIP Installation / Platform Change","included":False,
         "description":"Provision, install, or revise Cloud Inventory Platform components defined for this project.","details":""},
        {"key":"EPP","title":"Enterprise Printing Platform (EPP)","included":epp != "No",
         "description":"Configure the Enterprise Printing Platform components included in this project.","details":""},
        {"key":"BASELINE","title":"Baseline Application Changes","included":bool(baseline),
         "description":"Configure or modify the following Cloud Inventory Platform application components.","details":"\n".join(baseline)},
        {"key":"CUSTOM","title":"Develop and Deliver Custom Applications","included":bool(custom),
         "description":"Develop and configure the custom application scope defined for this project.","details":"\n".join(custom)},
        {"key":"LABELS","title":"Develop, Deploy and Configure Labels","included":bool(labels or (inp and inp.label_count)),
         "description":"Develop and configure labels defined by the approved project requirements.","details":"\n".join(labels) or (f"{int(inp.label_count)} label(s)" if inp and inp.label_count else "")},
        {"key":"SECURITY","title":"Configure for User Security","included":security != "None",
         "description":"Configure security-related components included in this project. Customer remains responsible for user and role administration unless expressly stated otherwise.","details":security if security != "None" else ""},
        {"key":"INTEGRATION","title":"Configure Integration and Connection Strings","included":bool(integrations or (inp and inp.gateway)),
         "description":"Configure the integration, connection, and service-definition components included in this project.","details":"\n".join(integrations)},
    ]

def _default_deliverables(db: Session, rev: EstimateRevision) -> list[dict]:
    return _cip_default_deliverables(db, rev) if revision_product(db, rev) == PRODUCT_CIP else _mep_default_deliverables(db, rev)

def _config_for_sow(db: Session, sow: SOW, rev: EstimateRevision, create: bool = True) -> SmallProjectSOWConfig | None:
    cfg = db.query(SmallProjectSOWConfig).filter(SmallProjectSOWConfig.sow_id == sow.id).first()
    if cfg or not create:
        return cfg
    cfg = SmallProjectSOWConfig(
        sow_id=sow.id,
        contracting_entity=rev.entity or "Data Systems International, Inc. dba Cloud Inventory®",
        mep_install_mode="",
        epp_deployment_model="",
        key_user_count=2,
        deliverables_json=_json_dump(_default_deliverables(db, rev)),
        methodology_json=_json_dump(_default_methodology()),
    )
    db.add(cfg)
    db.flush()
    return cfg

def create_small_project_sow(db: Session, rev: EstimateRevision, user: User) -> SOW:
    if not small_project_eligible(db, rev):
        raise ValueError("A Small Project SOW requires an approved Install Base estimate with Project Type = Small Project.")
    existing = sow_service.latest_sow(db, rev.id)
    if existing:
        return existing
    product = revision_product(db, rev)
    tmpl = _active_template(db, product)
    sow = SOW(
        estimate_revision_id=rev.id,
        template_version_id=tmpl.id,
        sow_revision_no=1,
        status="DRAFT",
        sow_date=date.today(),
        agreement_type=AGREEMENT_TYPES[0],
        invoice_frequency="Weekly",
        project_objective="",
        created_by=user.id,
    )
    db.add(sow)
    db.flush()
    _config_for_sow(db, sow, rev, create=True)
    support_hours = small_project_go_live_hours(db, rev)
    sites = max(int(rev.go_live_sites or 0), 0)
    for idx in range(sites if support_hours > 0 else 0):
        if rev.go_live_type == "On-Site All": support = "On-Site"
        elif rev.go_live_type == "On-Site Primary Remote Others": support = "On-Site" if idx == 0 else "Remote"
        else: support = "Remote"
        db.add(SOWHypercareLocation(sow_id=sow.id, support_type=support, sort_order=idx))
    record(
        db, event_type="SOW_CREATED", user_id=user.id, estimate_id=rev.estimate_id,
        revision_id=rev.id, field_name=f"SOW:{sow.id}", new_value="SOW Rev 1",
        reason=f"Pinned to {tmpl.label} v{tmpl.version_no}",
    )
    db.commit()
    return sow

def small_project_go_live_hours(db: Session, rev: EstimateRevision) -> float:
    for key, _, hours in _calc_lines(db, rev):
        if key in ("GO_LIVE_SUPPORT", "GOLIVE_SUPPORT"):
            return float(hours or 0)
    return 0.0

def _active_methodology(db: Session, cfg: SmallProjectSOWConfig, rev: EstimateRevision) -> dict[str, bool]:
    auto = methodology_auto(db, rev)
    rows = _json_load(cfg.methodology_json, _default_methodology())
    result = {}
    for row in rows:
        key = row.get("key")
        override = row.get("override", "AUTO")
        if override == "INCLUDE": result[key] = True
        elif override == "EXCLUDE": result[key] = False
        else: result[key] = bool(auto.get(key, False))
    result["HYPERCARE"] = bool(auto.get("HYPERCARE", False))
    return result

def _entity_options(db: Session, rev: EstimateRevision) -> list[str]:
    from .models import ConfigItem
    values = [
        x.label.strip() for x in db.query(ConfigItem)
        .filter(ConfigItem.config_version_id == rev.config_version_id, ConfigItem.category == "Entity", ConfigItem.active.is_(True))
        .order_by(ConfigItem.sort_order).all() if x.label.strip()
    ]
    for value in (rev.entity, "Data Systems International, Inc. dba Cloud Inventory®"):
        if value and value not in values: values.append(value)
    return values

def _active_approvers(db: Session) -> list[User]:
    return (
        db.query(User).join(UserRole, UserRole.user_id == User.id)
        .filter(User.active.is_(True), UserRole.role == "SOW_APPROVER")
        .order_by(User.username_normalized).all()
    )

def _context(db: Session, request: Request, core, sow: SOW, user):
    rev = sow_routes._rev_for_sow(db, sow)
    cfg = _config_for_sow(db, sow, rev, True)
    support_hours = small_project_go_live_hours(db, rev)
    allocated = sum(float(x.allocated_hours or 0) for x in sow.hypercare_locations)
    history = db.query(SOW).filter(SOW.estimate_revision_id == rev.id).order_by(desc(SOW.sow_revision_no)).all()
    users = {u.id: u.username for u in db.query(User).all()}
    auto = methodology_auto(db, rev)
    methods = _json_load(cfg.methodology_json, _default_methodology())
    for row in methods:
        row["auto_included"] = bool(auto.get(row.get("key"), False))
        override = row.get("override", "AUTO")
        row["effective_included"] = True if override == "INCLUDE" else False if override == "EXCLUDE" else row["auto_included"]
        row["locked_auto"] = row.get("key") == "HYPERCARE"
    return {
        "request": request, "user": user, "sow": sow, "cfg": cfg, "rev": rev, "estimate": rev.estimate,
        "active_tab": "sow", "readonly": sow.status != "DRAFT",
        "history": history, "approvers": _active_approvers(db), "users": users,
        "agreement_types": AGREEMENT_TYPES, "invoice_frequencies": INVOICE_FREQUENCIES,
        "support_types": SUPPORT_TYPES, "device_types": DEVICE_TYPES,
        "epp_deployment_models": EPP_DEPLOYMENT_MODELS, "mep_install_modes": MEP_INSTALL_MODES,
        "entity_options": _entity_options(db, rev),
        "deliverables": _json_load(cfg.deliverables_json, []), "methodology": methods,
        "go_live_support_hours": support_hours, "allocated_hours": allocated, "unallocated_hours": support_hours - allocated,
        "show_hypercare": support_hours > 0,
        "can_prepare": user.has_role(*PREP_ROLES),
        "can_approve": user.has_role("SOW_APPROVER") and sow.status == "PENDING_APPROVAL" and sow.approver_id == user.id,
        "product_type": revision_product(db, rev),
    }

def _as_int(v, default=0):
    try: return int(str(v).strip())
    except Exception: return default

def _as_float(v, default=0.0):
    try: return float(str(v).strip())
    except Exception: return default

def _replace_child_rows(db: Session, sow: SOW, form):
    db.query(SOWHypercareLocation).filter(SOWHypercareLocation.sow_id == sow.id).delete(synchronize_session=False)
    descs=form.getlist("hypercare_description"); countries=form.getlist("hypercare_country")
    support=form.getlist("hypercare_support_type"); hours=form.getlist("hypercare_hours")
    for idx in range(max(len(descs),len(countries),len(support),len(hours))):
        d=str(descs[idx] if idx<len(descs) else "").strip()
        c=str(countries[idx] if idx<len(countries) else "").strip()
        st=str(support[idx] if idx<len(support) else "Remote").strip() or "Remote"
        h=_as_float(hours[idx] if idx<len(hours) else 0)
        if not d and not c and h == 0: continue
        db.add(SOWHypercareLocation(sow_id=sow.id, description=d, country=c,
            support_type=st if st in SUPPORT_TYPES else "Remote", allocated_hours=h, sort_order=idx))
    db.query(SOWDevice).filter(SOWDevice.sow_id == sow.id).delete(synchronize_session=False)
    types=form.getlist("device_type"); models=form.getlist("device_make_model"); oses=form.getlist("device_os_version")
    for idx in range(max(len(types),len(models),len(oses))):
        typ=str(types[idx] if idx<len(types) else "Handheld Unit").strip() or "Handheld Unit"
        model=str(models[idx] if idx<len(models) else "").strip()
        osv=str(oses[idx] if idx<len(oses) else "").strip()
        if not model: continue
        db.add(SOWDevice(sow_id=sow.id, device_type=typ if typ in DEVICE_TYPES else "Other",
            make_model=model, os_version=osv, sort_order=idx))

def _save(db: Session, sow: SOW, rev: EstimateRevision, form):
    cfg = _config_for_sow(db, sow, rev, True)
    sow.agreement_type = str(form.get("agreement_type", sow.agreement_type)).strip()
    sow.invoice_frequency = str(form.get("invoice_frequency", sow.invoice_frequency)).strip()
    sow.project_objective = str(form.get("project_objective", sow.project_objective)).strip()
    sow.barcode_printer_count = _as_int(form.get("barcode_printer_count", sow.barcode_printer_count))
    for field in ("erp_version","erp_base_code_version","erp_tools_release","erp_os_version",
                  "erp_database_version","mep_product_version","epp_product_version","print_methods","erp_deployment_model"):
        setattr(sow, field, str(form.get(field, getattr(sow, field))).strip())
    cfg.contracting_entity = str(form.get("contracting_entity", cfg.contracting_entity)).strip()
    cfg.mep_install_mode = str(form.get("mep_install_mode", cfg.mep_install_mode)).strip()
    cfg.epp_deployment_model = str(form.get("epp_deployment_model", cfg.epp_deployment_model)).strip()
    cfg.key_user_count = max(1, _as_int(form.get("key_user_count", cfg.key_user_count), 2))
    titles=form.getlist("deliverable_title"); descriptions=form.getlist("deliverable_description")
    details=form.getlist("deliverable_details"); keys=form.getlist("deliverable_key")
    rows=[]
    for idx in range(max(len(titles),len(descriptions),len(details),len(keys))):
        title=str(titles[idx] if idx<len(titles) else "").strip()
        if not title: continue
        rows.append({
            "key":str(keys[idx] if idx<len(keys) else f"CUSTOM_{idx}").strip() or f"CUSTOM_{idx}",
            "title":title,
            "description":str(descriptions[idx] if idx<len(descriptions) else "").strip(),
            "details":str(details[idx] if idx<len(details) else "").strip(),
            "included":str(form.get(f"deliverable_included_{idx}", "")).lower() in ("1","true","yes","on"),
        })
    cfg.deliverables_json=_json_dump(rows)
    method_rows=[]
    for key,title in METHODS:
        override=str(form.get(f"method_override_{key}", "AUTO")).upper()
        if override not in METHOD_OVERRIDE_OPTIONS: override="AUTO"
        method_rows.append({"key":key,"title":title,"override":override})
    cfg.methodology_json=_json_dump(method_rows)
    _replace_child_rows(db, sow, form)

def validate_finalize(db: Session, sow: SOW, rev: EstimateRevision) -> list[str]:
    cfg = _config_for_sow(db, sow, rev, True)
    errors=[]
    if sow.agreement_type not in AGREEMENT_TYPES: errors.append("Select a valid Agreement Type.")
    if sow.invoice_frequency not in INVOICE_FREQUENCIES: errors.append("Select Weekly or Monthly invoice frequency.")
    if not cfg.contracting_entity.strip(): errors.append("Select a Contracting Entity.")
    if not sow.project_objective.strip(): errors.append("Project Objective is required.")
    included=[x for x in _json_load(cfg.deliverables_json, []) if x.get("included")]
    if not included: errors.append("Include at least one SOW deliverable.")
    for idx,row in enumerate(included,1):
        if not str(row.get("title","")).strip(): errors.append(f"Deliverable {idx} requires a name.")
        if not str(row.get("description","")).strip(): errors.append(f"Deliverable {idx} requires a Scope Description.")
    install=next((x for x in included if x.get("key")=="INSTALL"),None)
    if install and revision_product(db, rev)==PRODUCT_MEP and cfg.mep_install_mode not in ("Cloud","On-Premises"):
        errors.append("Select Cloud or On-Premises for the MEP installation/change deliverable.")
    epp=next((x for x in included if x.get("key")=="EPP"),None)
    if epp and cfg.epp_deployment_model not in EPP_DEPLOYMENT_MODELS:
        errors.append("Select Cloud or On-Premises for the EPP Deployment Model.")
    support_hours=small_project_go_live_hours(db, rev)
    allocated=sum(float(x.allocated_hours or 0) for x in sow.hypercare_locations)
    if support_hours > 0 and abs(allocated-support_hours)>0.01:
        errors.append(f"Hypercare allocations must equal the approved Go-Live Support hours ({support_hours:g}). Currently allocated: {allocated:g}.")
    if support_hours > 0:
        for idx,row in enumerate(sow.hypercare_locations,1):
            if row.allocated_hours > 0 and not row.description.strip(): errors.append(f"Hypercare location {idx} needs a Location Description.")
            if row.allocated_hours > 0 and not row.country.strip(): errors.append(f"Hypercare location {idx} needs a Country.")
    return errors

def _all_paragraphs(doc: Document):
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs
    for section in doc.sections:
        yield from section.header.paragraphs
        yield from section.footer.paragraphs
        for table in section.header.tables:
            for row in table.rows:
                for cell in row.cells: yield from cell.paragraphs
        for table in section.footer.tables:
            for row in table.rows:
                for cell in row.cells: yield from cell.paragraphs

def _set_text(p: Paragraph, text: str):
    if p.runs:
        p.runs[0].text=text
        for r in p.runs[1:]: r.text=""
    else:
        p.add_run(text)

def _replace_text_everywhere(doc: Document, replacements: dict[str,str]):
    for p in list(_all_paragraphs(doc)):
        text=p.text
        changed=False
        for old,new in replacements.items():
            if old in text:
                text=text.replace(old,new); changed=True
        if changed: _set_text(p,text)

def _heading_level(p: Paragraph) -> int | None:
    name=p.style.name if p.style else ""
    if not name.startswith("Heading "): return None
    try: return int(name.split()[-1])
    except Exception: return None

def _remove_block(doc: Document, heading_text: str):
    target=next((p for p in doc.paragraphs if p.text.strip()==heading_text),None)
    if not target: return
    level=_heading_level(target) or 3
    el=target._p
    parent=el.getparent()
    current=el
    while current is not None:
        nxt=current.getnext()
        parent.remove(current)
        if nxt is None: break
        if nxt.tag==qn("w:p"):
            p=Paragraph(nxt, doc)
            next_level=_heading_level(p)
            if next_level is not None and next_level <= level:
                break
        current=nxt

def _remove_from_paragraph_to_end(doc: Document, text: str):
    target=next((p for p in doc.paragraphs if p.text.strip()==text),None)
    if not target: return
    parent=target._p.getparent()
    current=target._p
    while current is not None:
        nxt=current.getnext()
        parent.remove(current)
        current=nxt

def _replace_objectives(doc: Document, text: str):
    targets=[p for p in doc.paragraphs if p.text.strip() in ("Objective1","Objective 1","Objective 2","Objective 3")]
    if not targets: return
    lines=[x.strip() for x in text.splitlines() if x.strip()] or [text.strip()]
    first=targets[0]
    _set_text(first, lines[0] if lines else "")
    anchor=first._p
    for extra in lines[1:]:
        clone=deepcopy(first._p)
        ts=clone.findall(".//"+qn("w:t"))
        if ts:
            ts[0].text=extra
            for t in ts[1:]: t.text=""
        anchor.addnext(clone); anchor=clone
    for p in targets[1:]:
        if p._p.getparent() is not None: p._p.getparent().remove(p._p)

def _replace_deliverables(doc: Document, deliverables: list[dict], product: str, cfg: SmallProjectSOWConfig):
    end=next((p for p in doc.paragraphs if p.text.strip()=="Service Methodology"),None)
    start=next((p for p in doc.paragraphs if p.text.strip()=="Software Deliverables"),None)
    if not end or not start: return
    current=start._p.getnext()
    parent=start._p.getparent()
    while current is not None and current is not end._p:
        nxt=current.getnext(); parent.remove(current); current=nxt
    intro=end.insert_paragraph_before("Cloud Inventory® will deliver the following software components and related configurations:")
    intro.style="Normal"
    for row in [x for x in deliverables if x.get("included")]:
        title=str(row.get("title","")).strip()
        h=end.insert_paragraph_before(title); h.style="Heading 3"
        desc=str(row.get("description","")).strip()
        if desc:
            p=end.insert_paragraph_before(desc); p.style="List Paragraph"
        if row.get("key")=="INSTALL":
            mode=cfg.mep_install_mode if product==PRODUCT_MEP else "Cloud"
            if mode:
                p=end.insert_paragraph_before(f"Deployment model: {mode}"); p.style="List Paragraph"
        if row.get("key")=="EPP" and cfg.epp_deployment_model:
            p=end.insert_paragraph_before(f"EPP deployment model: {cfg.epp_deployment_model}"); p.style="List Paragraph"
        for line in [x.strip() for x in str(row.get("details","")).splitlines() if x.strip()]:
            p=end.insert_paragraph_before(line); p.style="List Paragraph"

def _insert_after_clone(p: Paragraph, text: str):
    clone=deepcopy(p._p)
    ts=clone.findall(".//"+qn("w:t"))
    if ts:
        ts[0].text=text
        for t in ts[1:]: t.text=""
    p._p.addnext(clone)

def _delete_table(table):
    if table._element.getparent() is not None: table._element.getparent().remove(table._element)

def _delete_row(table,row):
    table._tbl.remove(row._tr)

def _appendix_has_data(sow: SOW) -> bool:
    values=(sow.erp_version,sow.erp_base_code_version,sow.erp_tools_release,sow.erp_os_version,
            sow.erp_database_version,sow.mep_product_version,sow.epp_product_version,sow.print_methods,
            sow.erp_deployment_model)
    return any(str(x or "").strip() for x in values) or any(x.make_model.strip() for x in sow.devices)

def _fill_tables(doc: Document, sow: SOW, rev: EstimateRevision, cfg: SmallProjectSOWConfig, product: str, support_hours: float):
    htable=next((t for t in doc.tables if t.rows and t.rows[0].cells[0].text.strip()=="Location Description"),None)
    if htable:
        while len(htable.rows)>1: _delete_row(htable,htable.rows[-1])
        active=[x for x in sow.hypercare_locations if float(x.allocated_hours or 0)>0 or x.description.strip()]
        if support_hours<=0 or not active: _delete_table(htable)
        else:
            for row in active:
                cells=htable.add_row().cells
                cells[0].text=row.description; cells[1].text=row.support_type; cells[2].text=row.country
                cells[3].text=f"{float(row.allocated_hours or 0):g}"
    ctable=next((t for t in doc.tables if t.rows and "Approved Hourly Rate" in t.rows[0].cells[0].text),None)
    if ctable and len(ctable.rows)>1:
        ctable.rows[1].cells[0].text=f"${rev.billing_rate:,.2f}"
        ctable.rows[1].cells[1].text=f"{rev.calculated_hours:g}"
        ctable.rows[1].cells[2].text=f"${rev.calculated_fees:,.2f}"
    atable=next((t for t in doc.tables if t.rows and t.rows[0].cells[0].text.strip()=="Deployment Point"),None)
    if atable:
        if not _appendix_has_data(sow):
            _delete_table(atable)
            _remove_from_paragraph_to_end(doc,"Appendix A")
            return
        mapping={
            "Planned ERP Solution": f"{rev.erp} {sow.erp_version}".strip(),
            "Planned ERP Base Code Version": sow.erp_base_code_version,
            "Planned ERP Tools Release Version": sow.erp_tools_release,
            "Planned ERP Operating System Version": sow.erp_os_version,
            "Planned ERP Database Type / Version": sow.erp_database_version,
            "Planned Cloud Inventory® Product / Version": (("CIP " if product==PRODUCT_CIP else "MEP ")+sow.mep_product_version).strip(),
            "Planned Label Printing Solution": (f"EPP {sow.epp_product_version}".strip() if sow.epp_product_version.strip() else ""),
            "Planned Print Method": sow.print_methods,
            "Planned Deployment Model – Cloud Inventory® Product": (
                cfg.mep_install_mode if product==PRODUCT_MEP and cfg.mep_install_mode else
                "Cloud Inventory® Managed / Public Cloud" if product==PRODUCT_CIP else ""
            ),
            "Planned Deployment Model – ERP Solution": sow.erp_deployment_model,
        }
        for row in list(atable.rows)[1:]:
            left=row.cells[0].text.replace("\xa0"," ").strip()
            matched=next((value for label,value in mapping.items() if label in left),None)
            if matched is not None:
                if str(matched).strip(): row.cells[1].text=str(matched)
                else: _delete_row(atable,row)
        for row in list(atable.rows)[1:]:
            left=row.cells[0].text.replace("\xa0"," ").strip().casefold()
            if any(x in left for x in ("handheld units","vehicle mount units","desktop environment")):
                _delete_row(atable,row)
        for dev in sow.devices:
            if not dev.make_model.strip(): continue
            cells=atable.add_row().cells
            cells[0].text=dev.device_type
            cells[1].text=f"{dev.make_model} – {dev.os_version}" if dev.os_version.strip() else dev.make_model

def render_docx(db: Session, sow: SOW, rev: EstimateRevision) -> bytes:
    tmpl=db.get(SOWTemplateVersion,sow.template_version_id)
    if not tmpl: raise ValueError("The SOW template version no longer exists.")
    cfg=_config_for_sow(db,sow,rev,True)
    product=revision_product(db,rev)
    doc=Document(io.BytesIO(tmpl.content))
    _replace_text_everywhere(doc,SAFE_REPLACEMENTS)
    entity=cfg.contracting_entity.strip() or rev.entity or "Data Systems International, Inc. dba Cloud Inventory®"
    agreement_segment="Software as a Service Agreement: (< Select one or the other >)Software License, Services and Maintenance Agreement"
    dynamic={
        "<CustomerName>":rev.customer or "",
        "<CUSTOMERNAME>":rev.customer or "",
        "<99999999>":rev.estimate.estimate_number,
        "<Today>":sow.sow_date.strftime("%B %d, %Y"),
        "(Other DSI Entity)":entity,
        agreement_segment:sow.agreement_type,
    }
    _replace_text_everywhere(doc,dynamic)
    _replace_objectives(doc,sow.project_objective)
    deliverables=_json_load(cfg.deliverables_json,[])
    _replace_deliverables(doc,deliverables,product,cfg)
    active=_active_methodology(db,cfg,rev)
    for key,title in METHODS:
        if not active.get(key,False): _remove_block(doc,title)
    if product==PRODUCT_MEP:
        _remove_block(doc,"Nextworld EAP Platform Administrator and Key Users")
    if rev.erp != "Oracle JD Edwards E1":
        for p in list(doc.paragraphs):
            if p.text.strip().startswith("Customer is responsible for providing a JDE EnterpriseOne environment"):
                p._p.getparent().remove(p._p)
    user_count_text = "two (2)" if cfg.key_user_count == 2 else str(cfg.key_user_count)
    for p in list(doc.paragraphs):
        if "up to 5 users" in p.text:
            _set_text(p,p.text.replace("up to 5 users",f"up to {user_count_text} users"))
        if "up to two (2) key users" in p.text:
            _set_text(p,p.text.replace("up to two (2) key users",f"up to {user_count_text} key users"))
    if not any("125% of the Approved Hourly Rate" in p.text for p in doc.paragraphs):
        anchor=next((p for p in doc.paragraphs if p.text.strip().startswith("Approved Hourly Rate stated above is for work performed during standard business weekdays")),None)
        if anchor:
            _insert_after_clone(anchor,"Work performed on weekends or holidays will be billed at 125% of the Approved Hourly Rate and must be approved in advance by Customer and Cloud Inventory® management.")
    support_hours=small_project_go_live_hours(db,rev)
    _fill_tables(doc,sow,rev,cfg,product,support_hours)
    settings=doc.settings._element
    update=settings.find(qn("w:updateFields"))
    if update is None:
        update=OxmlElement("w:updateFields"); settings.append(update)
    update.set(qn("w:val"),"true")
    out=io.BytesIO(); doc.save(out); return out.getvalue()

def canonical_text(docx_bytes: bytes) -> str:
    return sow_service.canonical_text(docx_bytes)

def content_hash_for(db: Session, sow: SOW, rev: EstimateRevision):
    content=render_docx(db,sow,rev); text=canonical_text(content)
    return hashlib.sha256(text.encode("utf-8")).hexdigest(),text,content

def verify_approved_content(db: Session, sow: SOW, rev: EstimateRevision) -> bytes:
    digest,_,content=content_hash_for(db,sow,rev)
    if sow.status=="APPROVED" and sow.content_hash and digest!=sow.content_hash:
        raise ValueError("The regenerated SOW no longer matches the approved wording. Historical download has been blocked for audit safety.")
    return content

def render_pdf(db: Session, sow: SOW, rev: EstimateRevision) -> bytes:
    docx=verify_approved_content(db,sow,rev) if sow.status=="APPROVED" else render_docx(db,sow,rev)
    doc=Document(io.BytesIO(docx)); out=io.BytesIO()
    pdf=SimpleDocTemplate(out,pagesize=letter,rightMargin=.6*inch,leftMargin=.6*inch,topMargin=.65*inch,bottomMargin=.65*inch)
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SOWTitleSP",parent=styles["Title"],alignment=TA_CENTER,fontSize=20,leading=24,spaceAfter=12))
    story=[]
    if sow.status!="APPROVED":
        story += [RLParagraph(f"<b>{sow.status.replace('_',' ')}</b> — REVIEW COPY",styles["Normal"]),Spacer(1,8)]
    in_toc=False
    for child in doc.element.body.iterchildren():
        if child.tag==qn("w:p"):
            p=Paragraph(child,doc); text=p.text.strip()
            if text=="Table of Contents": in_toc=True; continue
            if in_toc:
                if text.startswith("This Statement of Work"):
                    in_toc=False
                elif text=="Project Objective":
                    in_toc=False
                else:
                    continue
            if not text: continue
            style_name=p.style.name if p.style else ""
            if text=="Statement Of Work": style=styles["SOWTitleSP"]
            elif style_name.startswith("Heading 1"): style=styles["Heading1"]
            elif style_name.startswith("Heading 2"): style=styles["Heading2"]
            elif style_name.startswith("Heading 3"): style=styles["Heading3"]
            else: style=styles["BodyText"]
            bullet="•" if style_name=="List Paragraph" else None
            story.append(RLParagraph(html.escape(text),style,bulletText=bullet)); story.append(Spacer(1,3))
        elif child.tag==qn("w:tbl"):
            table=DocxTable(child,doc)
            data=[[RLParagraph(html.escape(cell.text.strip()),styles["BodyText"]) for cell in row.cells] for row in table.rows]
            if not data: continue
            rt=Table(data,repeatRows=1,hAlign="LEFT")
            rt.setStyle(TableStyle([
                ("GRID",(0,0),(-1,-1),.35,colors.grey),
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e8eef1")),
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
            ]))
            story += [rt,Spacer(1,6)]
    pdf.build(story); return out.getvalue()

def _clone_rejected_config(db: Session, source: SOW, dest: SOW, rev: EstimateRevision):
    src=_config_for_sow(db,source,rev,False)
    if not src: return
    db.add(SmallProjectSOWConfig(
        sow_id=dest.id, contracting_entity=src.contracting_entity, mep_install_mode=src.mep_install_mode,
        epp_deployment_model=src.epp_deployment_model, key_user_count=src.key_user_count,
        deliverables_json=src.deliverables_json, methodology_json=src.methodology_json,
    ))

def register_small_project_sow(app, core):
    @app.on_event("startup")
    def seed_on_startup():
        db=SessionLocal()
        try: seed_small_project_templates(db)
        finally: db.close()

    existing_estimate=_take_route(app,"/estimate/{rid}/sow","GET")
    existing_create=_take_route(app,"/estimate/{rid}/sow/create","POST")
    existing_page=_take_route(app,"/sow/{sid}","GET")
    existing_save=_take_route(app,"/sow/{sid}/save","POST")
    existing_finalize=_take_route(app,"/sow/{sid}/finalize","POST")
    existing_approve=_take_route(app,"/sow/{sid}/approve","POST")
    existing_pdf=_take_route(app,"/sow/{sid}/pdf","GET")
    existing_docx=_take_route(app,"/sow/{sid}/docx","GET")
    existing_new_revision=_take_route(app,"/sow/{sid}/new-revision","POST")

    @app.get("/estimate/{rid}/sow",response_class=HTMLResponse)
    def estimate_dispatch(rid:int,request:Request,db:Session=Depends(get_db)):
        rev=core.revision_or_404(db,rid)
        if rev.project_type!="Small Project":
            return existing_estimate(rid,request,db)
        user=core.current_user(request,db)
        sow=sow_service.latest_sow(db,rid)
        if sow: return RedirectResponse(f"/sow/{sow.id}",303)
        return core.templates.TemplateResponse("small_project_sow_empty.html",{
            "request":request,"user":user,"rev":rev,"estimate":rev.estimate,"active_tab":"sow",
            "eligible":small_project_eligible(db,rev),"product_type":revision_product(db,rev),
        })

    @app.post("/estimate/{rid}/sow/create")
    def create_dispatch(rid:int,request:Request,db:Session=Depends(get_db)):
        rev=core.revision_or_404(db,rid)
        if rev.project_type!="Small Project":
            return existing_create(rid,request,db)
        user=core.current_user(request,db); core.require_role(user,*PREP_ROLES)
        try: sow=create_small_project_sow(db,rev,user)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
        return RedirectResponse(f"/sow/{sow.id}",303)

    @app.get("/sow/{sid}",response_class=HTMLResponse)
    def page_dispatch(sid:int,request:Request,db:Session=Depends(get_db)):
        sow=sow_routes._sow_or_404(db,sid)
        if not is_small_project_sow(db,sow): return existing_page(sid,request,db)
        user=core.current_user(request,db)
        return core.templates.TemplateResponse("small_project_sow.html",_context(db,request,core,sow,user))

    @app.post("/sow/{sid}/save")
    async def save_dispatch(sid:int,request:Request,db:Session=Depends(get_db)):
        sow=sow_routes._sow_or_404(db,sid)
        if not is_small_project_sow(db,sow): return await existing_save(sid,request,db)
        user=core.current_user(request,db); core.require_role(user,*PREP_ROLES)
        rev=sow_routes._rev_for_sow(db,sow)
        if sow.status!="DRAFT": raise HTTPException(409,"Only a Draft SOW can be edited.")
        form=await request.form(); _save(db,sow,rev,form)
        record(db,event_type="SOW_FIELD_CHANGED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,
               field_name=f"SOW:{sow.id}:SMALL_PROJECT_DETAILS",new_value="Saved")
        db.commit(); return RedirectResponse(f"/sow/{sid}",303)

    @app.post("/sow/{sid}/finalize")
    def finalize_dispatch(sid:int,request:Request,db:Session=Depends(get_db)):
        sow=sow_routes._sow_or_404(db,sid)
        if not is_small_project_sow(db,sow): return existing_finalize(sid,request,db)
        user=core.current_user(request,db); core.require_role(user,*PREP_ROLES)
        rev=sow_routes._rev_for_sow(db,sow)
        if sow.status!="DRAFT": raise HTTPException(409,"Only a Draft SOW can be finalized.")
        errors=validate_finalize(db,sow,rev)
        if errors:
            field_map=[]
            joined=" ".join(errors)
            checks={
                "Agreement Type":"agreement_type","Contracting Entity":"contracting_entity",
                "Project Objective":"project_objective","deliverable":"deliverable_title",
                "Scope Description":"deliverable_description","MEP installation":"mep_install_mode",
                "EPP Deployment Model":"epp_deployment_model","Hypercare":"hypercare_hours",
            }
            for phrase,field in checks.items():
                if phrase.casefold() in joined.casefold() and field not in field_map: field_map.append(field)
            raise HTTPException(400,{"message":joined,"fields":field_map})
        sow.status="FINALIZED"; sow.finalized_by=user.id; sow.finalized_at=datetime.utcnow()
        record(db,event_type="SOW_FINALIZED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,
               field_name=f"SOW:{sow.id}",old_value="DRAFT",new_value="FINALIZED")
        db.commit(); return RedirectResponse(f"/sow/{sid}",303)

    @app.post("/sow/{sid}/approve")
    def approve_dispatch(sid:int,request:Request,db:Session=Depends(get_db)):
        sow=sow_routes._sow_or_404(db,sid)
        if not is_small_project_sow(db,sow): return existing_approve(sid,request,db)
        user=core.current_user(request,db)
        if not user.has_role("SOW_APPROVER"): raise HTTPException(403,"SOW Approver role required")
        rev=sow_routes._rev_for_sow(db,sow)
        if sow.status!="PENDING_APPROVAL": raise HTTPException(409,"Only a SOW Pending Approval can be approved.")
        if sow.approver_id!=user.id: raise HTTPException(403,"This SOW is assigned to another approver.")
        if sow.submitted_by==user.id: raise HTTPException(409,"The SOW submitter cannot approve their own SOW.")
        digest,text,_=content_hash_for(db,sow,rev)
        sow.status="APPROVED"; sow.approved_by=user.id; sow.approved_at=datetime.utcnow()
        sow.content_hash=digest; sow.approved_text_snapshot=text
        record(db,event_type="SOW_APPROVED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,
               field_name=f"SOW:{sow.id}",old_value="PENDING_APPROVAL",new_value="APPROVED",reason=f"Content hash {digest}")
        db.commit(); return RedirectResponse(f"/sow/{sid}",303)

    @app.get("/sow/{sid}/pdf")
    def pdf_dispatch(sid:int,request:Request,db:Session=Depends(get_db)):
        sow=sow_routes._sow_or_404(db,sid)
        if not is_small_project_sow(db,sow): return existing_pdf(sid,request,db)
        core.current_user(request,db); rev=sow_routes._rev_for_sow(db,sow)
        content=render_pdf(db,sow,rev)
        product=revision_product(db,rev)
        return Response(content,media_type="application/pdf",headers={
            "Content-Disposition":f'inline; filename="{rev.estimate.estimate_number}-{product}-Small-Project-SOW-R{sow.sow_revision_no}.pdf"'})

    @app.get("/sow/{sid}/docx")
    def docx_dispatch(sid:int,request:Request,db:Session=Depends(get_db)):
        sow=sow_routes._sow_or_404(db,sid)
        if not is_small_project_sow(db,sow): return existing_docx(sid,request,db)
        user=core.current_user(request,db); rev=sow_routes._rev_for_sow(db,sow)
        if sow.status!="APPROVED": raise HTTPException(409,"The Word SOW is available only after SOW approval.")
        try: content=verify_approved_content(db,sow,rev)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
        record(db,event_type="SOW_DOCX_GENERATED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,field_name=f"SOW:{sow.id}")
        db.commit(); product=revision_product(db,rev)
        return Response(content,media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",headers={
            "Content-Disposition":f'attachment; filename="{rev.estimate.estimate_number}-{product}-Small-Project-SOW-R{sow.sow_revision_no}.docx"'})

    @app.post("/sow/{sid}/new-revision")
    def new_revision_dispatch(sid:int,request:Request,db:Session=Depends(get_db)):
        source=sow_routes._sow_or_404(db,sid)
        if not is_small_project_sow(db,source): return existing_new_revision(sid,request,db)
        user=core.current_user(request,db); core.require_role(user,*PREP_ROLES)
        rev=sow_routes._rev_for_sow(db,source)
        try: dest=sow_service.copy_rejected_sow(db,source,rev,user)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
        if dest.id!=source.id and not db.query(SmallProjectSOWConfig).filter(SmallProjectSOWConfig.sow_id==dest.id).first():
            _clone_rejected_config(db,source,dest,rev); db.commit()
        return RedirectResponse(f"/sow/{dest.id}",303)

from __future__ import annotations

import hashlib
import html
import io
import json
import re
import zipfile
from copy import deepcopy
from datetime import date, datetime

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
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph as RP, Spacer,
    Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents
from sqlalchemy import desc
from sqlalchemy.orm import Session

from . import sow_routes, sow_service
from .cip_domain import _take_route, revision_product
from .cip_models import CIPRevisionInput, PRODUCT_CIP, PRODUCT_MEP
from .cip_sow.core import cip_go_live_support_hours, cip_scope_lists
from .database import get_db
from .models import EstimateRevision, User
from .services.audit import record
from .sow_models import SOW, SOWHypercareLocation, SOWTemplateVersion
from .small_project_models import (
    SMALL_PROJECT_INSTALL_MODES,
    SMALL_PROJECT_METHODOLOGY_MODES,
    SmallProjectSOWConfig,
    SmallProjectSOWDeliverable,
    SmallProjectSOWMethodology,
)
from .small_project_sow import (
    SOW_TEMPLATE_CIP_SMALL_PROJECT,
    SOW_TEMPLATE_MEP_SMALL_PROJECT,
)

SMALL_PROJECT_TEMPLATE_KEYS = (
    SOW_TEMPLATE_MEP_SMALL_PROJECT,
    SOW_TEMPLATE_CIP_SMALL_PROJECT,
)
APPROVED_ESTIMATE_STATUSES = ("APPROVED", "FINAL", "SUPERSEDED")
WEEKEND_HOLIDAY_CLAUSE = "Billed at 125% of the Approved Hourly Rate."

DELIVERABLE_SPECS = {
    PRODUCT_MEP: (
        ("MEP_INSTALL", "MEP Installation"),
        ("EPP", "Enterprise Printing Platform (EPP)"),
        ("BASELINE_APPS", "Deploy Baseline Applications"),
        ("CUSTOM_APPS", "Develop and Deliver Custom Applications"),
        ("LABELS", "Develop, Deploy and Configure Labels"),
        ("SECURITY", "Configure for User Security"),
        ("INTEGRATIONS", "Configure Integration and Connection Strings"),
    ),
    PRODUCT_CIP: (
        ("CIP_INSTALL", "CIP Installation"),
        ("EPP", "Enterprise Printing Platform (EPP)"),
        ("BASELINE_APPS", "Deploy Baseline Applications"),
        ("CUSTOM_APPS", "Develop and Deliver Custom Applications"),
        ("REPORTS", "Develop and Deliver Reports"),
        ("LABELS", "Develop, Deploy and Configure Labels"),
        ("SECURITY", "Configure for User Security"),
        ("INTEGRATIONS", "Configure Integration and Connection Strings"),
    ),
}

METHODOLOGY_SPECS = (
    ("PLANNING", "Project Planning Session"),
    ("KICKOFF", "Project Kickoff Meeting"),
    ("ADW", "Architecture Design Workshop (ADW)"),
    ("REQUIREMENTS", "Requirement Definition"),
    ("DEPLOYMENT", "Solution Application Deployment"),
    ("UNIT_TESTING", "Unit Testing"),
    ("DEVICE_CONFIG", "Mobile Client Device Configuration"),
    ("KEY_USER_TRAINING", "Key User Training"),
    ("UAT", "Support User Acceptance Testing"),
    ("LIMITED_LOAD_TEST", "Limited Load Test"),
    ("GO_LIVE_PREP", "Prepare for Go Live"),
    ("HYPERCARE", "Hypercare"),
)
METHODOLOGY_TITLE_TO_KEY = {title: key for key, title in METHODOLOGY_SPECS}


def _product_for_revision(db: Session, rev: EstimateRevision) -> str:
    return revision_product(db, rev)


def small_project_estimate_eligible(db: Session, rev: EstimateRevision) -> bool:
    if rev.status not in APPROVED_ESTIMATE_STATUSES:
        return False
    if rev.customer_type != "Install_Base":
        return False
    if _product_for_revision(db, rev) == PRODUCT_CIP:
        inp = db.get(CIPRevisionInput, rev.id)
        return bool(inp and inp.project_type == "Small Project")
    return rev.project_type == "Small Project"


def _template_key_for_product(product: str) -> str:
    return (
        SOW_TEMPLATE_CIP_SMALL_PROJECT
        if product == PRODUCT_CIP
        else SOW_TEMPLATE_MEP_SMALL_PROJECT
    )


def _template_for_sow(db: Session, sow: SOW) -> SOWTemplateVersion:
    row = db.get(SOWTemplateVersion, sow.template_version_id)
    if not row:
        raise ValueError("The SOW template version no longer exists.")
    return row


def is_small_project_sow(db: Session, sow: SOW) -> bool:
    try:
        return _template_for_sow(db, sow).template_key in SMALL_PROJECT_TEMPLATE_KEYS
    except ValueError:
        return False


def _active_template(db: Session, product: str) -> SOWTemplateVersion:
    key = _template_key_for_product(product)
    row = (
        db.query(SOWTemplateVersion)
        .filter(
            SOWTemplateVersion.template_key == key,
            SOWTemplateVersion.status == "ACTIVE",
        )
        .order_by(desc(SOWTemplateVersion.version_no))
        .first()
    )
    if not row:
        raise ValueError(f"No active {product} Small Project SOW template is available.")
    return row


def _config(db: Session, sow: SOW) -> SmallProjectSOWConfig:
    row = (
        db.query(SmallProjectSOWConfig)
        .filter(SmallProjectSOWConfig.sow_id == sow.id)
        .first()
    )
    if not row:
        raise ValueError("Small Project SOW configuration is not available.")
    return row


def _selected_mep_scope(db: Session, rev: EstimateRevision) -> dict[str, list[str]]:
    baseline = sow_service.selected_baseline_apps(db, rev)
    custom = sow_service.selected_custom_apps(db, rev)
    integrations: list[str] = []
    if rev.gateway:
        integrations.append("MEP Gateway")
    if rev.erp_integration_required and rev.erp_integration_count:
        integrations.append(f"{int(rev.erp_integration_count)} ERP service definition(s)")
    if rev.data_rep_required and rev.data_rep_count:
        integrations.append(f"{int(rev.data_rep_count)} data replication session(s)")
    if rev.iot_required and rev.iot_count:
        integrations.append(f"{int(rev.iot_count)} automation/service interface(s)")
    return {
        "baseline": baseline,
        "custom": custom,
        "labels": [f"{int(rev.label_count)} label template(s)"] if rev.labels_required and rev.label_count else [],
        "integrations": integrations,
    }


def _scope_sentence(values: list[str], empty: str) -> str:
    clean = [str(x).strip() for x in values if str(x).strip()]
    return "; ".join(clean) if clean else empty


def _deliverable_defaults(
    db: Session, rev: EstimateRevision, product: str
) -> dict[str, tuple[bool, str]]:
    if product == PRODUCT_CIP:
        inp = db.get(CIPRevisionInput, rev.id)
        if not inp:
            raise ValueError("CIP estimate inputs are not available.")
        scope = cip_scope_lists(db, rev)
        return {
            "CIP_INSTALL": (False, "Provision and configure Cloud Inventory Platform components defined for this Small Project."),
            "EPP": (
                inp.epp_install != "No",
                f"Install and configure EPP ({inp.epp_install})." if inp.epp_install != "No" else "No EPP work is included by default.",
            ),
            "BASELINE_APPS": (
                bool(scope["baseline"]),
                _scope_sentence(scope["baseline"], "No baseline application changes are included by default."),
            ),
            "CUSTOM_APPS": (
                bool(scope["custom"]),
                _scope_sentence(scope["custom"], "No custom application work is included by default."),
            ),
            "REPORTS": (
                bool(scope["reports"]),
                _scope_sentence(scope["reports"], "No report development is included by default."),
            ),
            "LABELS": (
                bool(scope["labels"]),
                _scope_sentence(scope["labels"], "No label development is included by default."),
            ),
            "SECURITY": (
                inp.security_method != "None",
                f"Configure solution security using {inp.security_method}." if inp.security_method != "None" else "No security configuration change is included by default.",
            ),
            "INTEGRATIONS": (
                bool(scope["integrations"]),
                _scope_sentence(scope["integrations"], "No integration changes are included by default."),
            ),
        }

    scope = _selected_mep_scope(db, rev)
    return {
        "MEP_INSTALL": (False, "Install mode is selected separately when platform installation is required."),
        "EPP": (
            rev.epp_install != "No",
            f"Install and configure EPP ({rev.epp_install})." if rev.epp_install != "No" else "No EPP work is included by default.",
        ),
        "BASELINE_APPS": (
            bool(scope["baseline"]),
            _scope_sentence(scope["baseline"], "No baseline application changes are included by default."),
        ),
        "CUSTOM_APPS": (
            bool(scope["custom"]),
            _scope_sentence(scope["custom"], "No custom application work is included by default."),
        ),
        "LABELS": (
            bool(scope["labels"]),
            _scope_sentence(scope["labels"], "No label development is included by default."),
        ),
        "SECURITY": (
            rev.security_method != "None",
            f"Configure solution security using {rev.security_method}." if rev.security_method != "None" else "No security configuration change is included by default.",
        ),
        "INTEGRATIONS": (
            bool(scope["integrations"]),
            _scope_sentence(scope["integrations"], "No integration changes are included by default."),
        ),
    }


def _go_live_inputs(db: Session, rev: EstimateRevision, product: str):
    if product == PRODUCT_CIP:
        inp = db.get(CIPRevisionInput, rev.id)
        if not inp:
            raise ValueError("CIP estimate inputs are not available.")
        return int(inp.go_live_sites or 0), inp.go_live_type
    return int(rev.go_live_sites or 0), rev.go_live_type


def small_project_support_hours(db: Session, rev: EstimateRevision, product: str) -> float:
    return (
        cip_go_live_support_hours(db, rev)
        if product == PRODUCT_CIP
        else sow_service.go_live_support_hours(db, rev)
    )


def create_small_project_sow(db: Session, rev: EstimateRevision, user: User) -> SOW:
    if not small_project_estimate_eligible(db, rev):
        raise ValueError(
            "A Small Project SOW is available only for an approved Install Base estimate with Project Type Small Project."
        )
    existing = sow_service.latest_sow(db, rev.id)
    if existing:
        return existing

    product = _product_for_revision(db, rev)
    template = _active_template(db, product)
    sow = SOW(
        estimate_revision_id=rev.id,
        template_version_id=template.id,
        sow_revision_no=1,
        status="DRAFT",
        sow_date=date.today(),
        agreement_type=sow_service.AGREEMENT_TYPES[0],
        invoice_frequency="Weekly",
        project_objective=(
            "Customer has requested changes to existing platform and/or application functionality. "
            "Cloud Inventory® will deliver the professional services and solution components defined in this SOW."
        ),
        created_by=user.id,
    )
    db.add(sow)
    db.flush()

    cfg = SmallProjectSOWConfig(
        sow_id=sow.id,
        install_mode="None",
        key_user_training_count=2,
    )
    db.add(cfg)
    db.flush()

    defaults = _deliverable_defaults(db, rev, product)
    for index, (key, name) in enumerate(DELIVERABLE_SPECS[product]):
        include, description = defaults[key]
        db.add(
            SmallProjectSOWDeliverable(
                config_id=cfg.id,
                deliverable_key=key,
                include=include,
                name=name,
                scope_description=description,
                detail_notes="",
                sort_order=index,
            )
        )
    for index, (key, _title) in enumerate(METHODOLOGY_SPECS):
        db.add(
            SmallProjectSOWMethodology(
                config_id=cfg.id,
                methodology_key=key,
                mode="Auto",
                sort_order=index,
            )
        )

    sites, go_live_type = _go_live_inputs(db, rev, product)
    for index in range(max(sites, 0)):
        if go_live_type == "On-Site All":
            support = "On-Site"
        elif go_live_type == "On-Site Primary Remote Others":
            support = "On-Site" if index == 0 else "Remote"
        else:
            support = "Remote"
        db.add(
            SOWHypercareLocation(
                sow_id=sow.id,
                support_type=support,
                sort_order=index,
            )
        )

    record(
        db,
        event_type="SOW_CREATED",
        user_id=user.id,
        estimate_id=rev.estimate_id,
        revision_id=rev.id,
        field_name=f"SOW:{sow.id}",
        new_value="SOW Rev 1",
        reason=f"Pinned to {template.label} v{template.version_no}",
    )
    db.commit()
    return sow

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from lxml import etree
from pypdf import PdfReader

from app.run import app
from app import sow_service
from app.cip_models import CIPRevisionInput
from app.cip_sow.core import SOW_TEMPLATE_CIP_NET_NEW
from app.cip_sow.docx import verify_cip_approved_content
from app.database import SessionLocal
from app.models import EstimateRevision, User, UserRole
from app.small_project_models import SmallProjectSOWConfig
from app.small_project_sow import (
    SOW_TEMPLATE_CIP_SMALL_PROJECT,
    SOW_TEMPLATE_MEP_SMALL_PROJECT,
)
from app.sp_render_b import verify_small_project_approved_content
from app.sow_models import SOW, SOW_TEMPLATE_MEP_NET_NEW
from app.sow_word_control import NS, W_NS


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


FAMILY_CASES = [
    ("MEP", False, SOW_TEMPLATE_MEP_NET_NEW, "MEP New Client Statement of Work", "mep-net-new"),
    ("CIP", False, SOW_TEMPLATE_CIP_NET_NEW, "CIP New Client Statement of Work", "cip-net-new"),
    ("MEP", True, SOW_TEMPLATE_MEP_SMALL_PROJECT, "MEP Small Project Statement of Work", "mep-small-project"),
    ("CIP", True, SOW_TEMPLATE_CIP_SMALL_PROJECT, "CIP Small Project Statement of Work", "cip-small-project"),
]

FAMILIES = [
    pytest.param(product, small_project, template, heading, id=case_id)
    for product, small_project, template, heading, case_id in FAMILY_CASES
]


def _login(client: TestClient, username: str = "Admin", password: str = "TestPass123!") -> None:
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)


def _new_estimate(client: TestClient, product: str) -> int:
    response = client.post(
        "/estimates/new",
        data={"product_type": product},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)
    return int(response.headers["location"].rstrip("/").rsplit("/", 1)[-1])


def _ensure_admin_can_be_selected_as_sow_approver() -> int:
    with SessionLocal() as db:
        admin = db.query(User).filter(User.username_normalized == "admin").one()
        exists = (
            db.query(UserRole)
            .filter(UserRole.user_id == admin.id, UserRole.role == "SOW_APPROVER")
            .first()
        )
        if not exists:
            db.add(UserRole(user_id=admin.id, role="SOW_APPROVER"))
            db.commit()
        return admin.id


def _approver(client: TestClient, slug: str) -> tuple[int, str, str]:
    username = f"MatrixApprover{slug}"
    password = "MatrixReviewPass123!"
    email = f"{slug.lower()}-matrix-approver@example.com"
    with SessionLocal() as db:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            return existing.id, username, password

    response = client.post(
        "/admin/users/create",
        data={
            "username": username,
            "email": email,
            "password": password,
            "active": "1",
            "roles": "SOW_APPROVER",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one()
        assert user.has_role("SOW_APPROVER")
        return user.id, username, password


def _prepare_approved_estimate(
    rid: int,
    product: str,
    small_project: bool,
    family_label: str,
) -> None:
    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        assert rev is not None
        rev.status = "APPROVED"
        rev.customer = f"{family_label} Matrix Customer"
        rev.customer_type = "Install_Base" if small_project else "Net_New"
        rev.entity = 'Data Systems International, Inc. dba Cloud Inventory® ("Cloud Inventory")'
        rev.billing_rate = 250
        rev.currency = "US Dollars"
        rev.go_live_sites = 0
        rev.go_live_type = "None"

        if product == "MEP":
            rev.erp = "SAP S/4HANA"
            rev.epp_install = "No"
            rev.project_type = "Small Project" if small_project else "MEP Cloud"
        else:
            inp = db.get(CIPRevisionInput, rid)
            assert inp is not None
            rev.project_type = "Small Project" if small_project else "CIP Install"
            inp.project_type = "Small Project" if small_project else "CIP Install"
            inp.deployed_over = "Standalone"
            inp.epp_install = "No"
            inp.go_live_sites = 0
            inp.go_live_type = "None"

        db.commit()


def _small_project_form(db, sow: SOW, product: str) -> dict[str, str]:
    cfg = (
        db.query(SmallProjectSOWConfig)
        .filter(SmallProjectSOWConfig.sow_id == sow.id)
        .one()
    )
    target = next(
        row for row in cfg.deliverables if row.deliverable_key == "BASELINE_APPS"
    )
    form = {
        "agreement_type": "Software as a Service Agreement",
        "invoice_frequency": "Monthly",
        "project_objective": f"Controlled {product} Small Project matrix objective.",
        "erp_version": "2023 FPS02",
        "install_mode": "None",
        "key_user_training_count": "0",
        f"deliverable_include_{target.id}": "on",
        f"deliverable_scope_{target.id}": "Configure approved baseline application scope.",
        f"deliverable_notes_{target.id}": "Four-family matrix regression evidence.",
    }
    for row in cfg.methodologies:
        form[f"methodology_mode_{row.id}"] = "Auto"
    return form


def _save_form(sid: int, product: str, small_project: bool) -> dict[str, str]:
    if small_project:
        with SessionLocal() as db:
            return _small_project_form(db, db.get(SOW, sid), product)

    if product == "MEP":
        return {
            "agreement_type": "Software as a Service Agreement",
            "invoice_frequency": "Monthly",
            "project_objective": "Controlled MEP Net New matrix objective.",
            "erp_version": "2023 FPS02",
            "mep_product_version": "MEP Current Version",
            "erp_deployment_model": "Customer Managed / Private Cloud",
            "barcode_printer_count": "0",
        }

    return {
        "agreement_type": "Software as a Service Agreement",
        "invoice_frequency": "Monthly",
        "project_objective": "Controlled CIP Net New matrix objective.",
        "barcode_printer_count": "0",
    }


def _assert_pdf_draft_state(content: bytes, *, draft: bool) -> None:
    reader = PdfReader(io.BytesIO(content))
    assert reader.pages
    page_text = [(page.extract_text() or "") for page in reader.pages]
    if draft:
        assert all("DRAFT" in text for text in page_text)
    else:
        assert all("DRAFT" not in text for text in page_text)


def _assert_word_controls(content: bytes, *, draft: bool) -> None:
    with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
        settings = etree.fromstring(archive.read("word/settings.xml"))
        document = etree.fromstring(archive.read("word/document.xml"))
        headers = [
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("word/header")
        ]

    protection = settings.find("w:documentProtection", namespaces=NS)
    assert settings.find("w:trackRevisions", namespaces=NS) is not None
    assert protection is not None
    assert protection.get(_w("edit")) == "trackedChanges"
    assert protection.get(_w("enforcement")) == "1"
    assert protection.get(_w("algorithmName")) == "SHA-512"
    assert document.findall(".//w:ins", namespaces=NS) == []
    assert document.findall(".//w:del", namespaces=NS) == []

    watermark_count = sum(raw.count(b"PowerPlusWaterMarkObject") for raw in headers)
    if draft:
        assert watermark_count >= 2
    else:
        assert watermark_count == 0


def _verified_approved_raw(
    db,
    sow: SOW,
    rev: EstimateRevision,
    product: str,
    small_project: bool,
) -> bytes:
    if small_project:
        return verify_small_project_approved_content(db, sow, rev)
    if product == "CIP":
        return verify_cip_approved_content(db, sow, rev)
    return sow_service.verify_approved_content(db, sow, rev)


@pytest.mark.parametrize(
    "product,small_project,expected_template,expected_heading",
    FAMILIES,
)
def test_four_family_sow_lifecycle_documents_and_historical_fidelity(
    product: str,
    small_project: bool,
    expected_template: str,
    expected_heading: str,
):
    slug = f"{product}{'SP' if small_project else 'NN'}"
    with TestClient(app) as client:
        _login(client)
        admin_id = _ensure_admin_can_be_selected_as_sow_approver()
        approver_id, approver_username, approver_password = _approver(client, slug)

        rid = _new_estimate(client, product)
        _prepare_approved_estimate(rid, product, small_project, expected_template)

        empty = client.get(f"/estimate/{rid}/sow")
        assert empty.status_code == 200
        assert "Prepare SOW" in empty.text or "Ready to Author" in empty.text

        created = client.post(f"/estimate/{rid}/sow/create", follow_redirects=False)
        assert created.status_code == 303, (created.status_code, created.text)
        sid = int(created.headers["location"].rstrip("/").rsplit("/", 1)[-1])

        with SessionLocal() as db:
            sow = db.get(SOW, sid)
            assert sow is not None
            assert sow.status == "DRAFT"
            assert sow.template_version.template_key == expected_template
            pinned_template_id = sow.template_version_id
            pinned_template_version = sow.template_version.version_no
            assert sow.template_version.status == "ACTIVE"

        page = client.get(f"/sow/{sid}")
        assert page.status_code == 200
        assert expected_heading in page.text
        for _, _, other_template, other_heading, _ in FAMILY_CASES:
            if other_template != expected_template:
                assert other_heading not in page.text

        saved = client.post(
            f"/sow/{sid}/save",
            data=_save_form(sid, product, small_project),
            follow_redirects=False,
        )
        assert saved.status_code == 303, (saved.status_code, saved.text)

        draft_pdf = client.get(f"/sow/{sid}/pdf")
        assert draft_pdf.status_code == 200
        assert draft_pdf.content.startswith(b"%PDF")
        _assert_pdf_draft_state(draft_pdf.content, draft=True)

        draft_word = client.get(f"/sow/{sid}/docx")
        assert draft_word.status_code == 200, (
            draft_word.status_code,
            draft_word.text if draft_word.status_code != 200 else "",
        )
        _assert_word_controls(draft_word.content, draft=True)

        finalized = client.post(f"/sow/{sid}/finalize", follow_redirects=False)
        assert finalized.status_code == 303, (finalized.status_code, finalized.text)

        self_send = client.post(
            f"/sow/{sid}/send-approval",
            data={"approver_id": str(admin_id)},
            follow_redirects=False,
        )
        assert self_send.status_code == 409
        assert "cannot approve their own SOW" in self_send.text

        sent = client.post(
            f"/sow/{sid}/send-approval",
            data={"approver_id": str(approver_id)},
            follow_redirects=False,
        )
        assert sent.status_code == 303, (sent.status_code, sent.text)

        client.post("/logout", follow_redirects=False)
        _login(client, approver_username, approver_password)

        missing_reason = client.post(
            f"/sow/{sid}/reject",
            data={"reason": ""},
            follow_redirects=False,
        )
        assert missing_reason.status_code == 400
        assert "rejection reason is required" in missing_reason.text

        rejected = client.post(
            f"/sow/{sid}/reject",
            data={"reason": "Four-family regression requires revision evidence."},
            follow_redirects=False,
        )
        assert rejected.status_code == 303

        client.post("/logout", follow_redirects=False)
        _login(client)

        revised = client.post(f"/sow/{sid}/new-revision", follow_redirects=False)
        assert revised.status_code == 303, (revised.status_code, revised.text)
        sid2 = int(revised.headers["location"].rstrip("/").rsplit("/", 1)[-1])

        with SessionLocal() as db:
            source = db.get(SOW, sid)
            dest = db.get(SOW, sid2)
            assert source.status == "REJECTED"
            assert dest.status == "DRAFT"
            assert dest.sow_revision_no == source.sow_revision_no + 1
            assert dest.template_version_id == pinned_template_id
            assert dest.template_version.version_no == pinned_template_version
            assert dest.template_version.template_key == expected_template
            assert dest.project_objective == source.project_objective

        assert client.post(f"/sow/{sid2}/finalize", follow_redirects=False).status_code == 303
        assert client.post(
            f"/sow/{sid2}/send-approval",
            data={"approver_id": str(approver_id)},
            follow_redirects=False,
        ).status_code == 303

        client.post("/logout", follow_redirects=False)
        _login(client, approver_username, approver_password)
        approved = client.post(f"/sow/{sid2}/approve", follow_redirects=False)
        assert approved.status_code == 303, (approved.status_code, approved.text)

        with SessionLocal() as db:
            sow = db.get(SOW, sid2)
            rev = db.get(EstimateRevision, rid)
            assert sow.status == "APPROVED"
            assert sow.template_version_id == pinned_template_id
            assert len(sow.content_hash or "") == 64
            assert sow.approved_text_snapshot

            raw1 = _verified_approved_raw(db, sow, rev, product, small_project)
            raw2 = _verified_approved_raw(db, sow, rev, product, small_project)
            text1 = sow_service.canonical_text(raw1)
            text2 = sow_service.canonical_text(raw2)
            digest = hashlib.sha256(text1.encode("utf-8")).hexdigest()
            assert text1 == text2
            assert digest == sow.content_hash
            assert text1 == sow.approved_text_snapshot

        approved_pdf = client.get(f"/sow/{sid2}/pdf")
        assert approved_pdf.status_code == 200
        _assert_pdf_draft_state(approved_pdf.content, draft=False)

        approved_word = client.get(f"/sow/{sid2}/docx")
        assert approved_word.status_code == 200, (
            approved_word.status_code,
            approved_word.text if approved_word.status_code != 200 else "",
        )
        _assert_word_controls(approved_word.content, draft=False)


def test_four_family_shared_routes_have_one_final_dispatch_boundary():
    expected = {
        ("/estimate/{rid}/sow", "GET"),
        ("/estimate/{rid}/sow/create", "POST"),
        ("/sow/{sid}", "GET"),
        ("/sow/{sid}/save", "POST"),
        ("/sow/{sid}/finalize", "POST"),
        ("/sow/{sid}/send-approval", "POST"),
        ("/sow/{sid}/approve", "POST"),
        ("/sow/{sid}/reject", "POST"),
        ("/sow/{sid}/new-revision", "POST"),
        ("/sow/{sid}/pdf", "GET"),
        ("/sow/{sid}/docx", "GET"),
    }
    for path, method in expected:
        matches = [
            route
            for route in app.routes
            if getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        ]
        assert len(matches) == 1, (
            path,
            method,
            [getattr(route, "name", None) for route in matches],
        )

"""Cross-family SOW release gates focused on the Small Project lifecycle gaps.

Net New MEP/CIP lifecycle coverage already lives in the focused SOW tests.  These
scenarios prove the two Small Project families cross the same controlled approval,
revision, PDF and Word boundaries without intercepting one another.
"""

from __future__ import annotations

from io import BytesIO
import zipfile

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.run import app
from app.cip_models import CIPRevisionInput
from app.database import SessionLocal
from app.models import EstimateRevision, User, UserRole
from app.sow_models import SOW
from app.small_project_models import SmallProjectSOWConfig
from app.small_project_sow import (
    SOW_TEMPLATE_CIP_SMALL_PROJECT,
    SOW_TEMPLATE_MEP_SMALL_PROJECT,
)
from app.small_project_workflow import small_project_content_hash_for


def _login(client, username="Admin", password="TestPass123!"):
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)


def _create_user(client, username: str, role: str, password: str) -> int:
    response = client.post(
        "/admin/users/create",
        data={
            "username": username,
            "email": f"{username.casefold()}@example.com",
            "password": password,
            "active": "1",
            "roles": role,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def _create_small_project_estimate(client, product: str, customer: str) -> int:
    response = client.post(
        "/estimates/new",
        data={"product_type": product},
        follow_redirects=False,
    )
    assert response.status_code == 303
    rid = int(response.headers["location"].rsplit("/", 1)[-1])
    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        rev.status = "APPROVED"
        rev.customer = customer
        rev.customer_type = "Install_Base"
        rev.project_type = "Small Project"
        rev.entity = 'Data Systems International, Inc. dba Cloud Inventory® ("Cloud Inventory")'
        rev.billing_rate = 250
        rev.currency = "US Dollars"
        rev.calculated_hours = 12
        rev.calculated_fees = 3000
        rev.go_live_sites = 0
        rev.go_live_type = "None"
        if product == "CIP":
            inp = db.get(CIPRevisionInput, rid)
            assert inp is not None
            inp.project_type = "Small Project"
            inp.go_live_sites = 0
            inp.go_live_type = "None"
        db.commit()
    return rid


def _create_and_finalize_small_project_sow(client, rid: int, scope: str) -> int:
    created = client.post(f"/estimate/{rid}/sow/create", follow_redirects=False)
    assert created.status_code == 303, (created.status_code, created.text)
    sid = int(created.headers["location"].rsplit("/", 1)[-1])
    with SessionLocal() as db:
        sow = db.get(SOW, sid)
        cfg = (
            db.query(SmallProjectSOWConfig)
            .filter(SmallProjectSOWConfig.sow_id == sid)
            .one()
        )
        row = cfg.deliverables[0]
        row.include = True
        row.scope_description = scope
        sow.project_objective = "Deliver the approved Small Project scope with controlled implementation services."
        db.commit()
    finalized = client.post(f"/sow/{sid}/finalize", follow_redirects=False)
    assert finalized.status_code == 303, (finalized.status_code, finalized.text)
    return sid


def _assert_word_controls(content: bytes, *, draft: bool) -> None:
    with zipfile.ZipFile(BytesIO(content), "r") as archive:
        settings = archive.read("word/settings.xml")
        headers = [
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("word/header") and name.endswith(".xml")
        ]
    assert b"trackRevisions" in settings
    assert b"documentProtection" in settings
    assert b"trackedChanges" in settings
    assert b'enforcement="1"' in settings or b"enforcement=\"1\"" in settings
    watermark_count = sum(raw.count(b"PowerPlusWaterMarkObject") for raw in headers)
    if draft:
        assert watermark_count > 0
    else:
        assert watermark_count == 0


def _pdf_has_draft(content: bytes) -> bool:
    reader = PdfReader(BytesIO(content))
    return any("DRAFT" in (page.extract_text() or "") for page in reader.pages)


def test_mep_small_project_shared_approval_rejection_revision_and_draft_controls():
    with TestClient(app) as client:
        _login(client)
        preparer_id = _create_user(
            client, "SPMatrixMEPPreparer", "ESTIMATOR", "PreparePass123!"
        )
        approver_id = _create_user(
            client, "SPMatrixMEPApprover", "SOW_APPROVER", "ApprovePass123!"
        )
        # Give the preparer SOW_APPROVER as a second role solely to prove the
        # send boundary still rejects self-assignment for Small Project SOWs.
        with SessionLocal() as db:
            db.add(UserRole(user_id=preparer_id, role="SOW_APPROVER"))
            db.commit()
        rid = _create_small_project_estimate(client, "MEP", "MEP SP Matrix Customer")

        client.post("/logout", follow_redirects=False)
        _login(client, "SPMatrixMEPPreparer", "PreparePass123!")
        sid = _create_and_finalize_small_project_sow(
            client, rid, "Configure the approved MEP Small Project application change."
        )

        with SessionLocal() as db:
            sow = db.get(SOW, sid)
            assert sow.template_version.template_key == SOW_TEMPLATE_MEP_SMALL_PROJECT
            template_version_id = sow.template_version_id

        self_assign = client.post(
            f"/sow/{sid}/send-approval",
            data={"approver_id": str(preparer_id)},
            follow_redirects=False,
        )
        assert self_assign.status_code == 409
        assert "cannot approve their own SOW" in self_assign.text

        sent = client.post(
            f"/sow/{sid}/send-approval",
            data={"approver_id": str(approver_id)},
            follow_redirects=False,
        )
        assert sent.status_code == 303

        client.post("/logout", follow_redirects=False)
        _login(client, "SPMatrixMEPApprover", "ApprovePass123!")
        blank = client.post(f"/sow/{sid}/reject", data={"reason": ""})
        assert blank.status_code == 400
        rejected = client.post(
            f"/sow/{sid}/reject",
            data={"reason": "Clarify the customer-specific scope before approval."},
            follow_redirects=False,
        )
        assert rejected.status_code == 303

        client.post("/logout", follow_redirects=False)
        _login(client, "SPMatrixMEPPreparer", "PreparePass123!")
        locked = client.post(
            f"/sow/{sid}/save",
            data={"project_objective": "Attempted rejected edit"},
            follow_redirects=False,
        )
        assert locked.status_code == 409

        revised = client.post(f"/sow/{sid}/new-revision", follow_redirects=False)
        assert revised.status_code == 303
        sid2 = int(revised.headers["location"].rsplit("/", 1)[-1])
        with SessionLocal() as db:
            new_sow = db.get(SOW, sid2)
            cfg = (
                db.query(SmallProjectSOWConfig)
                .filter(SmallProjectSOWConfig.sow_id == sid2)
                .one()
            )
            assert new_sow.status == "DRAFT"
            assert new_sow.sow_revision_no == 2
            assert new_sow.template_version_id == template_version_id
            assert new_sow.template_version.template_key == SOW_TEMPLATE_MEP_SMALL_PROJECT
            assert any(
                row.scope_description
                == "Configure the approved MEP Small Project application change."
                for row in cfg.deliverables
            )

        draft_pdf = client.get(f"/sow/{sid2}/pdf")
        assert draft_pdf.status_code == 200
        assert _pdf_has_draft(draft_pdf.content)

        draft_word = client.get(f"/sow/{sid2}/docx")
        assert draft_word.status_code == 200
        _assert_word_controls(draft_word.content, draft=True)


def test_cip_small_project_approval_hash_and_approved_document_controls():
    with TestClient(app) as client:
        _login(client)
        approver_id = _create_user(
            client, "SPMatrixCIPApprover", "SOW_APPROVER", "CIPApprovePass123!"
        )
        rid = _create_small_project_estimate(client, "CIP", "CIP SP Matrix Customer")
        sid = _create_and_finalize_small_project_sow(
            client, rid, "Configure the approved CIP Small Project application change."
        )

        with SessionLocal() as db:
            sow = db.get(SOW, sid)
            assert sow.template_version.template_key == SOW_TEMPLATE_CIP_SMALL_PROJECT

        sent = client.post(
            f"/sow/{sid}/send-approval",
            data={"approver_id": str(approver_id)},
            follow_redirects=False,
        )
        assert sent.status_code == 303

        client.post("/logout", follow_redirects=False)
        _login(client, "SPMatrixCIPApprover", "CIPApprovePass123!")
        approved = client.post(f"/sow/{sid}/approve", follow_redirects=False)
        assert approved.status_code == 303, (approved.status_code, approved.text)

        with SessionLocal() as db:
            sow = db.get(SOW, sid)
            rev = db.get(EstimateRevision, rid)
            assert sow.status == "APPROVED"
            assert sow.approved_by == approver_id
            assert len(sow.content_hash or "") == 64
            assert sow.approved_text_snapshot
            digest, text, _ = small_project_content_hash_for(db, sow, rev)
            assert digest == sow.content_hash
            assert text == sow.approved_text_snapshot

        approved_pdf = client.get(f"/sow/{sid}/pdf")
        assert approved_pdf.status_code == 200
        assert not _pdf_has_draft(approved_pdf.content)

        approved_word = client.get(f"/sow/{sid}/docx")
        assert approved_word.status_code == 200
        _assert_word_controls(approved_word.content, draft=False)

        # Approved content remains locked after the hash has been captured.
        locked = client.post(
            f"/sow/{sid}/save",
            data={"project_objective": "Attempted post-approval edit"},
            follow_redirects=False,
        )
        assert locked.status_code in (403, 409)

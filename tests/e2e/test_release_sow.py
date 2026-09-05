from __future__ import annotations

import io
import re
import zipfile

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader

from app.database import SessionLocal
from app.models import AuditEvent
from app.sow_models import SOW
from app.small_project_sow import SOW_TEMPLATE_CIP_SMALL_PROJECT, SOW_TEMPLATE_MEP_SMALL_PROJECT
from tests.e2e.support.flows import create_estimate, login, logout, select_and_save, url


pytestmark = [pytest.mark.e2e, pytest.mark.release]


def _approve_estimate(page, rid: int) -> None:
    page.get_by_role("button", name="Submit for Review").click()
    page.get_by_role("button", name="Approve / Final").click()
    expect(page.get_by_text("APPROVED", exact=True)).to_be_visible()


def _prepare_mep_net_new_sow(page, rid: int) -> int:
    page.get_by_role("link", name="SOW").click()
    page.get_by_role("button", name="Prepare SOW").click()
    sid = int(page.url.rstrip("/").rsplit("/", 1)[-1])
    page.get_by_label("ERP Version").fill("9.2.8")
    page.get_by_label("ERP Base Code Version").fill("E920")
    page.get_by_label("ERP Tools Release").fill("9.2.7.3")
    page.get_by_label("MEP Product Version").fill("9.5.0")
    page.get_by_label("ERP Deployment Model").fill("Customer Managed")
    page.get_by_role("button", name="Save SOW Details").click()
    return sid


def _send_to_approver(page, approver_name: str) -> None:
    page.get_by_role("button", name="Finalize SOW").click()
    page.get_by_label("Assign SOW Approver").select_option(label=approver_name)
    page.get_by_role("button", name="Send for Approval").click()


def _approve_sow_as(page, app_url: str, sid: int, spec) -> None:
    logout(page)
    login(page, app_url, spec.username, spec.password)
    page.goto(url(app_url, f"/sow/{sid}"))
    page.get_by_role("button", name="Approve SOW").click()
    expect(page.get_by_role("heading", name="Approved SOW")).to_be_visible()


def test_mep_net_new_sow_rejection_revision_approval_and_audit(page, app_url, user_specs):
    author = user_specs["multi"]
    approver = user_specs["sow_approver"]
    login(page, app_url, author.username, author.password)
    rid = create_estimate(page, app_url, "MEP")
    _approve_estimate(page, rid)
    sid = _prepare_mep_net_new_sow(page, rid)
    _send_to_approver(page, approver.username)

    denied = page.context.request.post(url(app_url, f"/sow/{sid}/approve"), fail_on_status_code=False, max_redirects=0)
    assert denied.status in (403, 409)

    logout(page)
    login(page, app_url, approver.username, approver.password)
    page.goto(url(app_url, f"/sow/{sid}"))
    page.get_by_label("Rejection Reason").fill("Controlled E2E rejection evidence")
    page.get_by_role("button", name="Reject SOW").click()
    expect(page.get_by_role("heading", name="Rejected")).to_be_visible()

    logout(page)
    login(page, app_url, author.username, author.password)
    page.goto(url(app_url, f"/sow/{sid}"))
    page.get_by_role("button", name="Create SOW Revision").click()
    sid2 = int(page.url.rstrip("/").rsplit("/", 1)[-1])
    assert sid2 != sid
    _send_to_approver(page, approver.username)
    _approve_sow_as(page, app_url, sid2, approver)

    with SessionLocal() as db:
        first = db.get(SOW, sid)
        second = db.get(SOW, sid2)
        assert first.status == "REJECTED"
        assert second.status == "APPROVED"
        assert second.template_version_id == first.template_version_id
        events = {row.event_type for row in db.query(AuditEvent).filter(AuditEvent.revision_id == rid).all()}
        assert {"SOW_REJECTED", "SOW_REVISION_CREATED", "SOW_APPROVED"}.issubset(events)


def test_mep_small_project_full_workflow(page, app_url, user_specs):
    author = user_specs["multi"]
    approver = user_specs["sow_approver"]
    login(page, app_url, author.username, author.password)
    rid = create_estimate(page, app_url, "MEP")
    select_and_save(page, rid, page.get_by_label("Customer Type:"), "Install_Base")
    select_and_save(page, rid, page.get_by_label("Project Type:"), "Small Project")
    _approve_estimate(page, rid)

    page.get_by_role("link", name="SOW").click()
    page.get_by_role("button", name="Prepare SOW").click()
    sid = int(page.url.rstrip("/").rsplit("/", 1)[-1])
    expect(page.get_by_role("heading", name="MEP Small Project Statement of Work")).to_be_visible()
    page.get_by_label("ERP / System Version").fill("9.2.8")
    deliverable = page.locator("tr").filter(has_text="Deploy Baseline Applications").first
    if deliverable.count() == 0:
        deliverable = page.locator("section").filter(has_text="Modular Deliverables").locator("tbody tr").first
    deliverable.locator('input[type="checkbox"]').check()
    page.get_by_role("button", name="Save SOW Details").click()
    _send_to_approver(page, approver.username)
    _approve_sow_as(page, app_url, sid, approver)

    with SessionLocal() as db:
        sow = db.get(SOW, sid)
        assert sow.status == "APPROVED"
        assert sow.template_version.template_key == SOW_TEMPLATE_MEP_SMALL_PROJECT


def test_cip_net_new_and_small_project_route_to_correct_sow_families(page, app_url, user_specs):
    author = user_specs["multi"]
    login(page, app_url, author.username, author.password)
    net_rid = create_estimate(page, app_url, "CIP")
    _approve_estimate(page, net_rid)
    page.get_by_role("link", name="SOW").click()
    page.get_by_role("button", name="Prepare SOW").click()
    net_sid = int(page.url.rstrip("/").rsplit("/", 1)[-1])
    expect(page.get_by_role("heading", name=re.compile("CIP.*Statement of Work"))).to_be_visible()

    page.goto(url(app_url, "/estimates/new"))
    page.get_by_role("button", name="Create CIP Estimate").click()
    sp_rid = int(page.url.rstrip("/").rsplit("/", 1)[-1])
    select_and_save(page, sp_rid, page.get_by_label("Customer Type:"), "Install_Base")
    select_and_save(page, sp_rid, page.get_by_label("Project Type:"), "Small Project")
    _approve_estimate(page, sp_rid)
    page.get_by_role("link", name="SOW").click()
    page.get_by_role("button", name="Prepare SOW").click()
    sp_sid = int(page.url.rstrip("/").rsplit("/", 1)[-1])
    expect(page.get_by_role("heading", name="CIP Small Project Statement of Work")).to_be_visible()

    with SessionLocal() as db:
        sp = db.get(SOW, sp_sid)
        assert sp.template_version.template_key == SOW_TEMPLATE_CIP_SMALL_PROJECT
        assert db.get(SOW, net_sid).template_version.template_key != SOW_TEMPLATE_CIP_SMALL_PROJECT


def test_representative_pdf_docx_draft_and_approved_controls(page, app_url, user_specs):
    author = user_specs["multi"]
    approver = user_specs["sow_approver"]
    login(page, app_url, author.username, author.password)
    rid = create_estimate(page, app_url, "MEP")
    _approve_estimate(page, rid)
    sid = _prepare_mep_net_new_sow(page, rid)

    draft_pdf = page.context.request.get(url(app_url, f"/sow/{sid}/pdf"))
    assert draft_pdf.status == 200
    draft_pdf_text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(draft_pdf.body())).pages)
    assert "DRAFT" in draft_pdf_text
    draft_docx = page.context.request.get(url(app_url, f"/sow/{sid}/docx"))
    assert draft_docx.status == 200
    with zipfile.ZipFile(io.BytesIO(draft_docx.body())) as zf:
        settings = zf.read("word/settings.xml").decode("utf-8")
        combined = "\n".join(zf.read(name).decode("utf-8", errors="ignore") for name in zf.namelist() if name.startswith("word/") and name.endswith(".xml"))
    assert "trackRevisions" in settings
    assert "documentProtection" in settings
    assert "DRAFT" in combined
    assert "E2E-TrackedChanges-2026!" not in combined

    _send_to_approver(page, approver.username)
    _approve_sow_as(page, app_url, sid, approver)
    approved_pdf = page.context.request.get(url(app_url, f"/sow/{sid}/pdf"))
    approved_pdf_text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(approved_pdf.body())).pages)
    assert "DRAFT" not in approved_pdf_text
    approved_docx = page.context.request.get(url(app_url, f"/sow/{sid}/docx"))
    with zipfile.ZipFile(io.BytesIO(approved_docx.body())) as zf:
        settings = zf.read("word/settings.xml").decode("utf-8")
        combined = "\n".join(zf.read(name).decode("utf-8", errors="ignore") for name in zf.namelist() if name.startswith("word/") and name.endswith(".xml"))
    assert "trackRevisions" in settings and "documentProtection" in settings
    assert "DRAFT" not in combined
    with SessionLocal() as db:
        sow = db.get(SOW, sid)
        assert sow.content_hash and sow.approved_text_snapshot

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from app.auth import normalize_username
from app.cip_domain import active_config_for_product
from app.cip_models import PRODUCT_CIP, PRODUCT_MEP
from app.database import SessionLocal
from app.models import AuditEvent, ConfigItem, ConfigurationVersion, EstimateRevision, User
from tests.e2e.support.flows import create_estimate, login, logout, url


pytestmark = [pytest.mark.e2e, pytest.mark.release]


def test_last_active_administrator_protection_through_user_ui(page, app_url, user_specs):
    admin = user_specs["admin"]
    with SessionLocal() as db:
        rows = db.query(User).filter(User.username_normalized != normalize_username(admin.username)).all()
        original = [(row.id, row.active) for row in rows if row.has_role("ADMIN")]
        for row in rows:
            if row.has_role("ADMIN"):
                row.active = False
        db.commit()

    try:
        login(page, app_url, admin.username, admin.password)
        page.get_by_role("link", name="Users").click()
        row = page.locator("tr").filter(has_text=admin.username).first
        row.get_by_text("Edit", exact=True).click()
        row.locator('input[name="active"]').uncheck()

        with page.expect_response(lambda r: "/admin/users/" in r.url and r.request.method == "POST") as pending:
            row.get_by_role("button", name="Save User").click()
        assert pending.value.status == 409
        expect(page.locator("#ciErrorModal")).to_be_visible()
        expect(page.locator("#ciErrorMessage")).to_contain_text("At least one active Administrator must remain")

        with SessionLocal() as db:
            persisted = db.query(User).filter(
                User.username_normalized == normalize_username(admin.username)
            ).one()
            assert persisted.active is True
            assert persisted.has_role("ADMIN")
    finally:
        with SessionLocal() as db:
            for uid, active in original:
                row = db.get(User, uid)
                if row:
                    row.active = active
            db.commit()


def test_revision_and_rebase_require_rationale_preserve_source_and_single_working_revision(
    page, app_url, user_specs
):
    actor = user_specs["multi"]
    login(page, app_url, actor.username, actor.password)
    rid = create_estimate(page, app_url, "MEP")
    page.get_by_role("button", name="Submit for Review").click()
    page.get_by_role("button", name="Approve / Final").click()

    with SessionLocal() as db:
        source = db.get(EstimateRevision, rid)
        source_customer = source.customer
        source_config = source.config_version_id
        estimate_id = source.estimate_id

    page.get_by_role("button", name="New Revision").click()
    expect(page.get_by_role("heading", name="Create New Revision")).to_be_visible()
    page.get_by_label("Reason for revision").fill("Customer requested controlled revision testing.")
    page.get_by_role("button", name="Create New Revision").click()
    rid2 = int(page.url.rstrip("/").rsplit("/", 1)[-1])

    with SessionLocal() as db:
        source = db.get(EstimateRevision, rid)
        working = db.get(EstimateRevision, rid2)
        assert source.status == "APPROVED"
        assert source.customer == source_customer
        assert working.status == "DRAFT"
        assert working.revision_no == 2
        assert working.config_version_id == source_config
        assert db.query(AuditEvent).filter_by(
            revision_id=rid2, event_type="REVISION_RATIONALE"
        ).one().reason == "Customer requested controlled revision testing."

    existing = page.context.request.post(
        url(app_url, f"/estimate/{rid}/new-revision?rebase=true"),
        form={"revision_reason": "Should reuse existing working revision."},
        max_redirects=0,
        fail_on_status_code=False,
    )
    assert existing.status == 303
    assert existing.headers["location"].endswith(f"/estimate/{rid2}")

    page.goto(url(app_url, f"/estimate/{rid2}"))
    page.get_by_role("button", name="Submit for Review").click()
    page.get_by_role("button", name="Approve / Final").click()
    page.get_by_role("button", name="Rebase to Current Model").click()
    expect(page.get_by_role("heading", name="Rebase to Current Model")).to_be_visible()
    page.get_by_label("Reason for revision").fill("Rebase to current controlled Calculation Data.")
    page.get_by_role("button", name="Create Rebased Revision").click()
    rid3 = int(page.url.rstrip("/").rsplit("/", 1)[-1])

    with SessionLocal() as db:
        source2 = db.get(EstimateRevision, rid2)
        rebased = db.get(EstimateRevision, rid3)
        assert source2.status == "APPROVED"
        assert rebased.status == "DRAFT"
        assert rebased.revision_no == 3
        assert db.query(EstimateRevision).filter(
            EstimateRevision.estimate_id == estimate_id,
            EstimateRevision.status.in_(("DRAFT", "REVIEW")),
        ).count() == 1
        rationale = db.query(AuditEvent).filter_by(
            revision_id=rid3, event_type="REVISION_RATIONALE"
        ).one()
        assert rationale.old_value == "REBASE"


def test_configuration_separation_of_duties_activation_and_historical_pin(
    page, app_url, user_specs
):
    admin = user_specs["admin"]
    reviewer = user_specs["tools"]
    login(page, app_url, admin.username, admin.password)
    historical_rid = create_estimate(page, app_url, "MEP")

    with SessionLocal() as db:
        historical = db.get(EstimateRevision, historical_rid)
        old_mep = active_config_for_product(db, PRODUCT_MEP)
        old_cip = active_config_for_product(db, PRODUCT_CIP)
        old_config_id = historical.config_version_id
        old_hours = historical.calculated_hours
        old_mep_id = old_mep.id
        old_cip_id = old_cip.id

    page.goto(url(app_url, "/data?product=MEP"))
    page.get_by_role("button", name="Create MEP Draft from Active").click()
    draft_id = int(parse_qs(urlparse(page.url).query)["version"][0])

    row = page.locator("tr").filter(has_text="UNIT_TEST_FACTOR").first
    row.get_by_text("Edit", exact=True).click()
    row.locator('input[name="value_number"]').fill("0.25")
    row.locator('input[name="reason"]').fill("E2E independent governance validation")
    row.get_by_role("button", name="Save").click()

    page.get_by_role("button", name="Submit for Review").click()
    expect(page.get_by_text("Independent review required.")).to_be_visible()

    self_review = page.context.request.post(
        url(app_url, f"/data/version/{draft_id}/review"),
        form={"action": "approve", "reason": "Self approval must fail"},
        max_redirects=0,
        fail_on_status_code=False,
    )
    assert self_review.status == 409

    logout(page)
    login(page, app_url, reviewer.username, reviewer.password)
    page.goto(url(app_url, f"/data?product=MEP&version={draft_id}"))
    approve_form = page.locator('form').filter(has_text="Approve Configuration")
    approve_form.get_by_label("Review reason").fill(
        "Independent calculation and regression evidence reviewed."
    )
    approve_form.get_by_role("button", name="Approve Configuration").click()
    page.get_by_role("button", name="Activate Approved Version").click()

    try:
        with SessionLocal() as db:
            version = db.get(ConfigurationVersion, draft_id)
            historical = db.get(EstimateRevision, historical_rid)
            assert version.status == "ACTIVE"
            assert db.get(ConfigurationVersion, old_mep_id).status == "RETIRED"
            assert active_config_for_product(db, PRODUCT_CIP).id == old_cip_id
            assert historical.config_version_id == old_config_id
            assert historical.calculated_hours == old_hours
            event_types = {
                row.event_type
                for row in db.query(AuditEvent).filter(AuditEvent.config_version_id == draft_id).all()
            }
            assert {
                "CONFIG_VERSION_CREATED",
                "CONFIG_VALUE_CHANGED",
                "CONFIG_VERSION_SUBMITTED",
                "CONFIG_VERSION_APPROVED",
                "CONFIG_VERSION_ACTIVATED",
            }.issubset(event_types)
    finally:
        with SessionLocal() as db:
            new = db.get(ConfigurationVersion, draft_id)
            old = db.get(ConfigurationVersion, old_mep_id)
            if new:
                new.status = "RETIRED"
                new.approval_status = "RETIRED"
            if old:
                old.status = "ACTIVE"
                old.approval_status = "ACTIVE"
            db.commit()

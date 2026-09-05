from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from app.cip_models import CIPNonBillableAllocation, CIPRevisionInput, EstimateProduct
from app.database import SessionLocal
from app.models import EstimateRevision
from app.services.cip_calculation_v101 import calculation as cip_calculation
from tests.e2e.support.flows import create_estimate, fill_and_blur, login, logout, select_and_save, url


pytestmark = [pytest.mark.e2e, pytest.mark.release]


@pytest.mark.smoke
def test_authentication_active_and_inactive(page, app_url, user_specs):
    active = user_specs["estimator"]
    login(page, app_url, active.username, active.password)
    expect(page.get_by_role("heading", name="Estimates")).to_be_visible()
    logout(page)

    inactive = user_specs["inactive"]
    page.goto(url(app_url, "/login"))
    page.get_by_label("Username").fill(inactive.username)
    page.get_by_label("Password").fill(inactive.password)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(re.compile(r".*/login$"))
    expect(page.get_by_text("Invalid username/password or inactive user")).to_be_visible()


@pytest.mark.smoke
def test_role_union_readonly_and_tools_admin_boundaries(page, app_url, user_specs):
    multi = user_specs["multi"]
    login(page, app_url, multi.username, multi.password)
    expect(page.get_by_role("link", name="Approvals")).to_be_visible()
    expect(page.get_by_role("link", name="+ New Estimate")).to_be_visible()
    logout(page)

    tools = user_specs["tools"]
    login(page, app_url, tools.username, tools.password)
    expect(page.get_by_role("link", name="Calculation Data")).to_be_visible()
    expect(page.get_by_role("link", name="SOW Templates")).to_be_visible()
    expect(page.get_by_role("link", name="Users")).to_have_count(0)
    denied = page.context.request.get(url(app_url, "/admin/users"), fail_on_status_code=False)
    assert denied.status == 403
    logout(page)

    readonly = user_specs["readonly"]
    login(page, app_url, readonly.username, readonly.password)
    denied = page.context.request.post(
        url(app_url, "/estimates/new"),
        form={"product_type": "MEP"},
        fail_on_status_code=False,
        max_redirects=0,
    )
    assert denied.status == 403


@pytest.mark.smoke
def test_mep_creation_pins_product_configuration_and_engine(page, app_url, user_specs):
    estimator = user_specs["estimator"]
    login(page, app_url, estimator.username, estimator.password)
    rid = create_estimate(page, app_url, "MEP")
    expect(page.get_by_text(re.compile(r"Estimate \d{9}"))).to_be_visible()
    expect(page.locator('input[name="product_type"]')).to_have_count(0)

    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        assert re.fullmatch(r"\d{9}", rev.estimate.estimate_number)
        assert db.get(EstimateProduct, rev.estimate_id).product_type == "MEP"
        assert rev.engine_version == "1.0.1"
        assert rev.config_version_id is not None


@pytest.mark.smoke
def test_mep_autosave_erp_reset_detail_adjustment_and_golden_reload(page, app_url, user_specs):
    estimator = user_specs["estimator"]
    login(page, app_url, estimator.username, estimator.password)
    rid = create_estimate(page, app_url, "MEP")

    fill_and_blur(page, rid, page.get_by_label("Number Of Go-Live Sites"), "1")
    select_and_save(page, rid, page.get_by_label("Go-Live Type"), "Remote All")

    jde = page.locator(".app-pair").filter(has_text="Cycle Count Directed").first.locator("select")
    select_and_save(page, rid, jde, "Mod Required")

    with page.expect_navigation(wait_until="domcontentloaded"):
        page.get_by_label("Deployed Over").select_option(label="Oracle Fusion")
    expect(page.get_by_text("Cycle Count Directed")).to_have_count(0)
    expect(page.get_by_text("Cycle Count", exact=True)).to_be_visible()

    fusion = page.locator(".app-pair").filter(has_text=re.compile(r"^Cycle Count")).first.locator("select")
    select_and_save(page, rid, fusion, "Mod Required")

    page.get_by_role("link", name="Estimate Detail").click()
    row = page.locator("tr").filter(has_text="Cycle Count").first
    row.locator('input[name^="mod_"]').fill("0.5")
    row.locator('input[name^="notes_"]').fill("Controlled half-hour browser regression")
    page.get_by_role("button", name="Save Detail").click()
    expect(row.locator(".line-total")).to_have_text("18.5")

    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        assert rev.calculated_hours == pytest.approx(163.5)
        assert rev.calculated_fees == pytest.approx(40875.0)

    page.reload()
    row = page.locator("tr").filter(has_text="Cycle Count").first
    expect(row.locator('input[name^="mod_"]')).to_have_value("0.5")
    expect(row.locator(".line-total")).to_have_text("18.5")


@pytest.mark.smoke
def test_cip_scope_quarter_hour_adjustments_and_nonbillable_semantics(page, app_url, user_specs):
    estimator = user_specs["estimator"]
    login(page, app_url, estimator.username, estimator.password)
    rid = create_estimate(page, app_url, "CIP")

    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        inp = db.get(CIPRevisionInput, rid)
        assert rev.engine_version == "CIP-1.0.1"
        assert inp.release_key == "RELEASE_26_2"

    desktop = page.locator(".app-pair").filter(has_text="INB Shipments").first.locator("select")
    select_and_save(page, rid, desktop, "Mod Required")
    page.get_by_role("link", name="Estimate Detail").click()

    row = page.locator("tr").filter(has_text="INB Shipments").first
    row.locator('input[name^="added_"]').fill("0.25")
    row.locator('input[name^="adjustment_notes_"]').fill("Quarter-hour development adjustment")
    row.locator('input[name^="test_adjust_"]').fill("0.25")
    row.locator('input[name^="test_notes_"]').fill("Quarter-hour testing adjustment")
    page.get_by_role("button", name="Save Detail Adjustments").click()

    page.get_by_role("link", name="Calculations").click()
    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        _, before, _, _ = cip_calculation(db, rev)

    kickoff = page.locator("tr").filter(has_text="Project Kickoff Meeting").first
    kickoff.locator('input[name^="nonbillable_"]').fill("4")
    kickoff.locator('input[name^="nonbillable_notes_"]').fill("Internal planning allocation")
    page.get_by_role("button", name="Save Calculation Adjustments").click()

    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        _, after, _, _ = cip_calculation(db, rev)
        allocation = db.query(CIPNonBillableAllocation).filter_by(
            revision_id=rid, line_key="PLAN_KICKOFF"
        ).one()
        assert allocation.hours == 4
        assert after["non_billable_hours"] == pytest.approx(before["non_billable_hours"] + 4)
        assert after["total_internal_hours"] == pytest.approx(
            after["investment_hours"] + after["non_billable_hours"]
        )
        # Governing v0.3.25.1 rules include non-billable Plan workload in Plan PM,
        # so only the PM overhead may move customer investment; the 4h allocation
        # itself is not added to the fee base.
        assert after["investment_hours"] < before["investment_hours"] + 4
        assert after["fees"] == pytest.approx(after["investment_hours"] * rev.billing_rate)

    page.reload()
    kickoff = page.locator("tr").filter(has_text="Project Kickoff Meeting").first
    expect(kickoff.locator('input[name^="nonbillable_"]')).to_have_value("4.0")


@pytest.mark.smoke
def test_estimate_lifecycle_locks_ui_and_server_mutation(page, app_url, user_specs):
    actor = user_specs["multi"]
    login(page, app_url, actor.username, actor.password)
    rid = create_estimate(page, app_url, "MEP")

    page.get_by_role("button", name="Submit for Review").click()
    expect(page.get_by_text("REVIEW", exact=True)).to_be_visible()
    page.get_by_role("button", name="Approve / Final").click()
    expect(page.get_by_text("APPROVED", exact=True)).to_be_visible()

    expect(page.get_by_label("Customer:")).to_be_disabled()
    denied = page.context.request.post(
        url(app_url, f"/estimate/{rid}"),
        form={"customer": "Forbidden Locked Mutation"},
        fail_on_status_code=False,
        max_redirects=0,
    )
    assert denied.status == 409

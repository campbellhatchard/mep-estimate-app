from __future__ import annotations

import pytest
from playwright.sync_api import expect

from app.cip_models import ConfigurationProduct, PRODUCT_MEP
from app.database import SessionLocal
from app.models import ConfigurationVersion, EstimateRevision
from app.runtime_time import utc_now
from app.sow_models import SOW, SOWTemplateVersion
from tests.e2e.support.flows import create_estimate, login, logout, url


pytestmark = [pytest.mark.e2e, pytest.mark.release]


def test_historical_estimate_and_sow_remain_pinned_after_new_config_and_template_activate(page, app_url, user_specs):
    author = user_specs["multi"]
    approver = user_specs["sow_approver"]
    login(page, app_url, author.username, author.password)
    rid = create_estimate(page, app_url, "MEP")
    page.get_by_role("button", name="Submit for Review").click()
    page.get_by_role("button", name="Approve / Final").click()
    page.get_by_role("link", name="SOW").click()
    page.get_by_role("button", name="Prepare SOW").click()
    sid = int(page.url.rstrip("/").rsplit("/", 1)[-1])
    page.get_by_label("ERP Version").fill("9.2.8")
    page.get_by_label("ERP Base Code Version").fill("E920")
    page.get_by_label("ERP Tools Release").fill("9.2.7.3")
    page.get_by_label("MEP Product Version").fill("9.5.0")
    page.get_by_label("ERP Deployment Model").fill("Customer Managed")
    page.get_by_role("button", name="Save SOW Details").click()
    page.get_by_role("button", name="Finalize SOW").click()
    page.get_by_label("Assign SOW Approver").select_option(label=approver.username)
    page.get_by_role("button", name="Send for Approval").click()
    logout(page)
    login(page, app_url, approver.username, approver.password)
    page.goto(url(app_url, f"/sow/{sid}"))
    page.get_by_role("button", name="Approve SOW").click()

    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid); sow = db.get(SOW, sid)
        old_config_id = rev.config_version_id; old_engine = rev.engine_version
        old_hours = rev.calculated_hours; old_fees = rev.calculated_fees
        old_template_id = sow.template_version_id; old_composition = sow.composition_version; old_hash = sow.content_hash
        old_config = db.get(ConfigurationVersion, old_config_id); old_template = db.get(SOWTemplateVersion, old_template_id)
        new_config = ConfigurationVersion(name=f"E2E Future MEP Config {rid}", status="ACTIVE", approval_status="ACTIVE", change_reason="Synthetic historical-pinning test configuration", created_by=rev.created_by, activated_at=utc_now())
        db.add(new_config); db.flush(); db.add(ConfigurationProduct(config_version_id=new_config.id, product_type=PRODUCT_MEP))
        old_config.status = "RETIRED"; old_config.approval_status = "RETIRED"
        new_template = SOWTemplateVersion(template_key=old_template.template_key, label=old_template.label, product_type=old_template.product_type, customer_type=old_template.customer_type, version_no=old_template.version_no + 1000, status="ACTIVE", filename=f"E2E_Future_{rid}.docx", content=old_template.content, content_sha256=old_template.content_sha256, change_reason="Synthetic historical template pin test", created_by=rev.created_by, activated_by=rev.created_by, activated_at=utc_now())
        db.add(new_template); old_template.status = "RETIRED"; db.commit()
        new_config_id = new_config.id; new_template_id = new_template.id

    try:
        page.goto(url(app_url, f"/estimate/{rid}"))
        expect(page.get_by_text(f"Config {old_config_id}" )).to_be_visible()
        expect(page.get_by_text(f"Engine {old_engine}" )).to_be_visible()
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid); sow = db.get(SOW, sid)
            assert rev.config_version_id == old_config_id and rev.engine_version == old_engine
            assert rev.calculated_hours == old_hours and rev.calculated_fees == old_fees
            assert sow.template_version_id == old_template_id and sow.composition_version == old_composition and sow.content_hash == old_hash
        assert page.context.request.get(url(app_url, f"/sow/{sid}/docx")).status == 200
    finally:
        with SessionLocal() as db:
            old_config = db.get(ConfigurationVersion, old_config_id); old_template = db.get(SOWTemplateVersion, old_template_id)
            new_config = db.get(ConfigurationVersion, new_config_id); new_template = db.get(SOWTemplateVersion, new_template_id)
            old_config.status = "ACTIVE"; old_config.approval_status = "ACTIVE"; old_template.status = "ACTIVE"
            if new_template: db.delete(new_template)
            if new_config: db.delete(new_config)
            db.commit()

from __future__ import annotations

import csv
import io

import pytest
from playwright.sync_api import expect

from app.database import SessionLocal
from app.jira_relationships import BLOCKS, jira_exportable_tasks
from app.models import AuditEvent, ScheduleTask
from tests.e2e.support.flows import create_estimate, fill_and_blur, login, url


pytestmark = [pytest.mark.e2e, pytest.mark.release]


def test_schedule_stale_export_preserves_manual_values_until_explicit_regeneration(
    page, app_url, user_specs
):
    estimator = user_specs["estimator"]
    login(page, app_url, estimator.username, estimator.password)
    rid = create_estimate(page, app_url, "MEP")

    page.get_by_role("link", name="Schedule").click()
    resource = page.locator('input[name^="resource_"]').first
    resource_name = resource.get_attribute("name")
    assert resource_name
    resource.fill("E2E Resource")
    page.get_by_role("button", name="Save Schedule Changes").click()
    expect(page.locator(f'input[name="{resource_name}"]')).to_have_value("E2E Resource")

    page.get_by_role("link", name="Estimate", exact=True).click()
    fill_and_blur(page, rid, page.get_by_label("Billing Rate:"), "260")
    page.get_by_role("link", name="Schedule").click()
    expect(page.get_by_text("Schedule Requires Refresh.")).to_be_visible()
    expect(page.locator(f'input[name="{resource_name}"]')).to_have_value("E2E Resource")

    exported = page.context.request.get(url(app_url, f"/estimate/{rid}/schedule.csv"))
    assert exported.status == 200
    text = exported.body().decode("utf-8-sig")
    assert "E2E Resource" in text

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Regenerate Schedule").click()
    expect(page.get_by_text("Schedule Requires Refresh.")).to_have_count(0)
    regenerated_resource = page.locator(f'input[name="{resource_name}"]')
    assert regenerated_resource.count() == 0 or regenerated_resource.first.input_value() != "E2E Resource"

    with SessionLocal() as db:
        assert db.query(AuditEvent).filter(
            AuditEvent.revision_id == rid,
            AuditEvent.event_type == "SCHEDULE_CSV_EXPORTED",
        ).count() >= 1


def test_jira_relationship_rules_capacity_cycle_and_csv_mapping(page, app_url, user_specs):
    estimator = user_specs["estimator"]
    login(page, app_url, estimator.username, estimator.password)
    rid = create_estimate(page, app_url, "MEP")
    page.get_by_role("link", name="Schedule").click()
    page.get_by_role("link", name="Jira Relationships").click()

    with SessionLocal() as db:
        tasks = db.query(ScheduleTask).filter(
            ScheduleTask.revision_id == rid
        ).order_by(ScheduleTask.sort_order, ScheduleTask.id).all()
        exportable = jira_exportable_tasks(tasks)
        assert len(exportable) >= 8
        task_ids = [row.id for row in exportable[:8]]
        source_task = exportable[0]
        first_target = exportable[1]
        source_name = source_task.task
        target_name = first_target.task

    page.get_by_label("Source Story").select_option(value=str(task_ids[0]))
    page.get_by_label("Relationship").select_option(value=BLOCKS)
    page.get_by_label("Target Story").select_option(value=str(task_ids[1]))
    page.get_by_role("button", name="Add Jira Relationship").click()
    expect(page.get_by_role("heading", name="Current Relationships")).to_be_visible()

    self_link = page.context.request.post(url(app_url, f"/estimate/{rid}/jira-relationships"), form={"action":"add","source_task_id":str(task_ids[0]),"target_task_id":str(task_ids[0]),"relationship_type":BLOCKS}, fail_on_status_code=False, max_redirects=0)
    assert self_link.status == 400
    duplicate = page.context.request.post(url(app_url, f"/estimate/{rid}/jira-relationships"), form={"action":"add","source_task_id":str(task_ids[0]),"target_task_id":str(task_ids[1]),"relationship_type":BLOCKS}, fail_on_status_code=False, max_redirects=0)
    assert duplicate.status == 409
    cycle = page.context.request.post(url(app_url, f"/estimate/{rid}/jira-relationships"), form={"action":"add","source_task_id":str(task_ids[1]),"target_task_id":str(task_ids[0]),"relationship_type":BLOCKS}, fail_on_status_code=False, max_redirects=0)
    assert cycle.status == 400

    for target_id in task_ids[2:7]:
        response = page.context.request.post(url(app_url, f"/estimate/{rid}/jira-relationships"), form={"action":"add","source_task_id":str(task_ids[0]),"target_task_id":str(target_id),"relationship_type":BLOCKS}, fail_on_status_code=False, max_redirects=0)
        assert response.status == 303
    overflow = page.context.request.post(url(app_url, f"/estimate/{rid}/jira-relationships"), form={"action":"add","source_task_id":str(task_ids[0]),"target_task_id":str(task_ids[7]),"relationship_type":BLOCKS}, fail_on_status_code=False, max_redirects=0)
    assert overflow.status == 409

    jira = page.context.request.get(url(app_url, f"/estimate/{rid}/jira.csv"))
    assert jira.status == 200
    rows = list(csv.reader(io.StringIO(jira.body().decode("utf-8-sig"))))
    assert len(rows[0]) == 27
    source_csv = next(row for row in rows[1:] if row[2] == source_name)
    assert source_csv[7] == target_name
    assert source_csv[8]

    with SessionLocal() as db:
        assert db.query(AuditEvent).filter(AuditEvent.revision_id == rid, AuditEvent.event_type == "JIRA_RELATIONSHIP_ADDED").count() == 6

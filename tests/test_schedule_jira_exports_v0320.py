from __future__ import annotations

import csv
from datetime import date
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AuditEvent, EstimateRevision, ScheduleTask
from app.run import app
from app.schedule_exports_runtime import JIRA_HEADERS, SCHEDULE_HEADERS


PRODUCTS = ("MEP", "CIP")


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "Admin", "password": "TestPass123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _create_estimate(client: TestClient, product: str) -> int:
    data = {"product_type": "CIP"} if product == "CIP" else {}
    response = client.post("/estimates/new", data=data, follow_redirects=False)
    assert response.status_code == 303, (response.status_code, response.text)
    return int(response.headers["location"].rstrip("/").rsplit("/", 1)[-1])


def _open_schedule(client: TestClient, rid: int) -> None:
    response = client.get(f"/estimate/{rid}/schedule")
    assert response.status_code == 200
    assert f'/estimate/{rid}/schedule.csv' in response.text
    assert f'/estimate/{rid}/jira.csv' in response.text


def _csv_rows(response):
    assert response.status_code == 200, (response.status_code, response.text)
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(StringIO(text)))


@pytest.mark.parametrize("product", PRODUCTS)
def test_schedule_csv_exports_current_persisted_mep_and_cip_edits_without_regeneration(product: str):
    with TestClient(app) as client:
        _login(client)
        rid = _create_estimate(client, product)
        _open_schedule(client, rid)

        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            task = (
                db.query(ScheduleTask)
                .filter(ScheduleTask.revision_id == rid, ScheduleTask.task != ScheduleTask.phase)
                .order_by(ScheduleTask.sort_order)
                .first()
            )
            assert task is not None
            task_id = task.task_id
            task.resource_assigned = f"{product} Persisted Resource"
            task.status = "In Progress"
            task.percent_complete = 50
            task.non_bill_hours = 4.5
            task.billable_hours_budgeted = 8.0
            task.change_order_hours = 2.0
            task.hours_used = 3.0
            task.comments = f"{product} persisted schedule comment"
            task.start_date = date(2026, 9, 1)
            task.end_date = date(2026, 9, 5)
            rev.schedule_needs_refresh = True
            task_count = db.query(ScheduleTask).filter(ScheduleTask.revision_id == rid).count()
            db.commit()

        response = client.get(f"/estimate/{rid}/schedule.csv")
        rows = _csv_rows(response)
        assert rows[0] == SCHEDULE_HEADERS
        values = next(row for row in rows[1:] if row[0] == task_id)
        data = dict(zip(SCHEDULE_HEADERS, values))

        assert data["Resource Assigned"] == f"{product} Persisted Resource"
        assert data["Status"] == "In Progress"
        assert float(data["Percent Complete"]) == 50.0
        assert float(data["Non-Billable Hours"]) == 4.5
        assert float(data["Billable Hours Budgeted"]) == 8.0
        assert float(data["Change Order Hours"]) == 2.0
        assert float(data["Hours Used"]) == 3.0
        assert float(data["Billable Hours Remaining"]) == 7.0
        assert data["Budget Trend / Health"] == "Trending Under"
        assert float(data["Estimate at Completion"]) == 6.0
        assert data["Comments"] == f"{product} persisted schedule comment"
        assert data["Start Date"] == "2026-09-01"
        assert data["End Date"] == "2026-09-05"

        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            task = (
                db.query(ScheduleTask)
                .filter(ScheduleTask.revision_id == rid, ScheduleTask.task_id == task_id)
                .first()
            )
            assert task is not None
            assert task.resource_assigned == f"{product} Persisted Resource"
            assert task.comments == f"{product} persisted schedule comment"
            assert rev.schedule_needs_refresh is True
            assert db.query(ScheduleTask).filter(ScheduleTask.revision_id == rid).count() == task_count
            event = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.revision_id == rid,
                    AuditEvent.event_type == "SCHEDULE_CSV_EXPORTED",
                )
                .order_by(AuditEvent.id.desc())
                .first()
            )
            assert event is not None
            assert "without regeneration" in (event.reason or "")
            assert "stale" in (event.reason or "")


@pytest.mark.parametrize("product", PRODUCTS)
def test_jira_export_preserves_27_columns_and_includes_nonbillable_only_schedule_work(product: str):
    with TestClient(app) as client:
        _login(client)
        rid = _create_estimate(client, product)
        _open_schedule(client, rid)

        summary = f"{product} Non-Billable Export Parity Task"
        with SessionLocal() as db:
            task = (
                db.query(ScheduleTask)
                .filter(ScheduleTask.revision_id == rid, ScheduleTask.task != ScheduleTask.phase)
                .order_by(ScheduleTask.sort_order)
                .first()
            )
            assert task is not None
            task.task = summary
            task.description = f"{product} deterministic Jira description"
            task.purpose = "Validate non-billable implementation work is retained"
            task.billable_hours_budgeted = 0.0
            task.non_bill_hours = 3.5
            task.change_order_hours = 1.0
            task.hours_used = 1.5
            phase = task.phase
            db.commit()

        response = client.get(f"/estimate/{rid}/jira.csv")
        rows = _csv_rows(response)
        assert rows[0] == JIRA_HEADERS
        assert len(rows[0]) == 27
        assert all(len(row) == 27 for row in rows[1:])

        story = next(row for row in rows[1:] if row[2] == summary)
        assert story[0] == "Story"
        assert f"{product} deterministic Jira description" in story[3]
        assert "Purpose / Goal: Validate non-billable implementation work is retained" in story[3]
        assert "Non-Billable Hours: 3.5" in story[3]
        assert story[4] == ""
        assert float(story[5]) == 3.5
        assert float(story[6]) == 3.0
        assert all(value == "" for value in story[7:25])
        assert story[25] != ""
        assert story[26] == phase

        with SessionLocal() as db:
            event = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.revision_id == rid,
                    AuditEvent.event_type == "JIRA_CSV_EXPORTED",
                )
                .order_by(AuditEvent.id.desc())
                .first()
            )
            assert event is not None
            assert "27-column" in (event.reason or "")
            assert "deferred" in (event.reason or "")


def test_schedule_csv_requires_an_existing_persisted_schedule_and_does_not_generate_one():
    with TestClient(app) as client:
        _login(client)
        rid = _create_estimate(client, "MEP")
        with SessionLocal() as db:
            assert db.query(ScheduleTask).filter(ScheduleTask.revision_id == rid).count() == 0

        response = client.get(f"/estimate/{rid}/schedule.csv")
        assert response.status_code == 409
        assert "has not been generated" in response.text

        with SessionLocal() as db:
            assert db.query(ScheduleTask).filter(ScheduleTask.revision_id == rid).count() == 0

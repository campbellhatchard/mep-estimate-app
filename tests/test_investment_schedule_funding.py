from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.cip_models import CIPNonBillableAllocation, CIPScopeItem
from app.database import SessionLocal
from app.models import EstimateRevision, ScheduleTask
from app.run import app
from app.services.cip_schedule import generate_cip_schedule


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "Admin", "password": "TestPass123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _create_cip(client: TestClient) -> int:
    response = client.post(
        "/estimates/new",
        data={"product_type": "CIP"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return int(response.headers["location"].rstrip("/").rsplit("/", 1)[-1])


def test_cip_schedule_keeps_152_task_hours_and_splits_52_investment_from_100_billable():
    with TestClient(app) as client:
        _login(client)
        revision_id = _create_cip(client)

        with SessionLocal() as db:
            revision = db.get(EstimateRevision, revision_id)
            desktop_rows = (
                db.query(CIPScopeItem)
                .filter(
                    CIPScopeItem.revision_id == revision_id,
                    CIPScopeItem.category == "DESKTOP",
                )
                .order_by(CIPScopeItem.sort_order, CIPScopeItem.id)
                .all()
            )
            assert len(desktop_rows) >= 19
            for row in desktop_rows[:19]:
                row.config_type = "Mod Required"
            db.add(
                CIPNonBillableAllocation(
                    revision_id=revision_id,
                    line_key="BUILD_DESKTOP_MOD",
                    hours=52.0,
                    notes="Approved Cloud Inventory investment",
                )
            )
            db.flush()

            tasks = generate_cip_schedule(db, revision, replace=True)
            development = next(task for task in tasks if task.task_id == "BUILD_DESKTOP_MOD")
            build_phase = next(task for task in tasks if task.task_id == "CIP-BUILD")

            # Schedule duration/effort continues to represent gross work to be delivered.
            assert development.start_date is not None
            assert development.end_date is not None
            gross_scheduled = development.billable_hours_budgeted + development.non_bill_hours
            assert gross_scheduled == pytest.approx(152.0)

            # Funding columns split the gross task 152 = 52 investment + 100 customer billable.
            assert development.non_bill_hours == pytest.approx(52.0)
            assert development.billable_hours_budgeted == pytest.approx(100.0)

            # Phase funding must reconcile the same way rather than counting investment twice.
            child_rows = [task for task in tasks if task.phase == "Build" and task.task_id != "CIP-BUILD"]
            assert build_phase.non_bill_hours == pytest.approx(sum(task.non_bill_hours for task in child_rows))
            assert build_phase.billable_hours_budgeted == pytest.approx(
                sum(task.billable_hours_budgeted for task in child_rows)
            )

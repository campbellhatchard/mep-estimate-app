from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import cip_routes_detail
from app.cip_models import CIPNonBillableAllocation, CIPScopeItem
from app.database import SessionLocal
from app.models import EstimateRevision
from app.run import app


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


def _line(lines, key: str):
    return next(line for line in lines if line.key == key)


def _set_152_desktop_development(db, revision_id: int) -> EstimateRevision:
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
    db.flush()
    return revision


def test_cip_investment_reclassifies_152_development_hours_without_changing_effort_or_overhead():
    """152 task hours funded 52 internally become 100 customer-billable hours.

    Investment is a funding allocation only. It must not add/remove task effort or
    change PM, contingency, preparation, testing, schedule effort, or other
    calculations whose basis is gross project effort.
    """
    with TestClient(app) as client:
        _login(client)
        revision_id = _create_cip(client)

        with SessionLocal() as db:
            revision = _set_152_desktop_development(db, revision_id)

            before_lines, before_summary, *_ = cip_routes_detail.cip_calculation(db, revision)
            development_before = _line(before_lines, "BUILD_DESKTOP_MOD")
            pm_before = _line(before_lines, "BUILD_PM")
            contingency_before = _line(before_lines, "BUILD_CONTINGENCY")

            assert development_before.task_hours == pytest.approx(152.0)

            db.add(
                CIPNonBillableAllocation(
                    revision_id=revision_id,
                    line_key="BUILD_DESKTOP_MOD",
                    hours=52.0,
                    notes="Approved Cloud Inventory investment",
                )
            )
            db.flush()

            after_lines, after_summary, *_ = cip_routes_detail.cip_calculation(db, revision)
            development_after = _line(after_lines, "BUILD_DESKTOP_MOD")
            pm_after = _line(after_lines, "BUILD_PM")
            contingency_after = _line(after_lines, "BUILD_CONTINGENCY")

            # Gross effort is unchanged.
            assert development_after.task_hours == pytest.approx(152.0)
            assert after_summary["total_internal_hours"] == pytest.approx(
                before_summary["total_internal_hours"]
            )

            # Funding is reclassified 152 task = 52 investment + 100 customer billable.
            assert development_after.investment_hours == pytest.approx(52.0)
            assert development_after.billable_hours == pytest.approx(100.0)
            assert after_summary["investment_hours"] == pytest.approx(
                before_summary["investment_hours"] + 52.0
            )
            assert after_summary["billable_hours"] == pytest.approx(
                before_summary["billable_hours"] - 52.0
            )

            # PM and contingency are effort-derived and therefore unchanged.
            assert pm_after.task_hours == pytest.approx(pm_before.task_hours)
            assert contingency_after.task_hours == pytest.approx(contingency_before.task_hours)

            # Customer fees follow customer-billable hours only.
            assert after_summary["fees"] == pytest.approx(
                before_summary["fees"] - 52.0 * float(revision.billing_rate)
            )


def test_cip_calculation_page_can_allocate_investment_to_build_without_changing_task_hours():
    """The funding control is available on any calculated effort line, not Plan only."""
    with TestClient(app) as client:
        _login(client)
        revision_id = _create_cip(client)

        with SessionLocal() as db:
            revision = _set_152_desktop_development(db, revision_id)
            cip_routes_detail.cip_recalculate_and_store(db, revision)
            db.commit()

        response = client.get(f"/estimate/{revision_id}/calculations")
        assert response.status_code == 200
        assert "Customer Billable Hours" in response.text
        assert "Investment Hours" in response.text

        match = re.search(
            r'name="line_key_(\d+)" value="BUILD_DESKTOP_MOD"',
            response.text,
        )
        assert match, "BUILD_DESKTOP_MOD calculation row must expose a stable line key"
        idx = int(match.group(1))
        line_count_match = re.search(r'name="line_count" value="(\d+)"', response.text)
        assert line_count_match

        payload = {
            "line_count": line_count_match.group(1),
            f"line_key_{idx}": "BUILD_DESKTOP_MOD",
            f"phase_{idx}": "Build",
            f"adjust_{idx}": "0",
            f"notes_{idx}": "",
            f"investment_{idx}": "52",
            f"investment_notes_{idx}": "Approved Cloud Inventory investment",
        }
        saved = client.post(
            f"/estimate/{revision_id}/calculations",
            data=payload,
            follow_redirects=False,
        )
        assert saved.status_code == 303

        with SessionLocal() as db:
            allocation = (
                db.query(CIPNonBillableAllocation)
                .filter_by(revision_id=revision_id, line_key="BUILD_DESKTOP_MOD")
                .one()
            )
            assert allocation.hours == pytest.approx(52.0)
            revision = db.get(EstimateRevision, revision_id)
            lines, summary, *_ = cip_routes_detail.cip_calculation(db, revision)
            development = _line(lines, "BUILD_DESKTOP_MOD")
            assert development.task_hours == pytest.approx(152.0)
            assert development.investment_hours == pytest.approx(52.0)
            assert development.billable_hours == pytest.approx(100.0)
            assert summary["task_hours"] == pytest.approx(summary["billable_hours"] + summary["investment_hours"])

        estimate_page = client.get(f"/estimate/{revision_id}")
        assert estimate_page.status_code == 200
        assert "Gross Task Hours" in estimate_page.text
        assert "Cloud Inventory Investment" in estimate_page.text
        assert "Customer Billable Hours" in estimate_page.text

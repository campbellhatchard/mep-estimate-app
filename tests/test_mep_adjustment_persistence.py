"""Save must persist the same summary that a fresh calculation will produce."""

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import CalculationAdjustment, DetailAdjustment, EstimateApplication, EstimateRevision
from app.run import app
from app.services.calculation_v101 import calculation, recalculate_and_store


@pytest.mark.parametrize("page", ["detail", "calculations"])
@pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
def test_mep_save_adjustment_synchronizes_persisted_summary(page, existing):
    with TestClient(app) as client:
        response = client.post("/login", data={"username": "Admin", "password": "TestPass123!"}, follow_redirects=False)
        assert response.status_code == 303
        response = client.post("/estimates/new", data={"product_type": "MEP"}, follow_redirects=False)
        assert response.status_code == 303
        rid = int(response.headers["location"].rsplit("/", 1)[-1])
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.project_type = "MEP On Prem"
            if page == "detail":
                application = db.query(EstimateApplication).filter_by(revision_id=rid, kind="APPLICATION").order_by(EstimateApplication.sort_order).first()
                application.config_type = "Mod Required"
                key = f"APP:{application.catalog_key}"
                model, attribute, field = DetailAdjustment, "mod_hours", "mod_0"
            else:
                key = "PLAN_ADW"
                model, attribute, field = CalculationAdjustment, "adjust_hours", "adjust_0"
            if existing:
                db.add(model(revision_id=rid, line_key=key, notes="Initial adjustment", **{attribute: 0.25}))
            db.flush()
            recalculate_and_store(db, rev)
            before_hours = rev.calculated_hours
            rev.schedule_needs_refresh = False
            db.commit()

        response = client.post(f"/estimate/{rid}/{page}", data={
            "line_count": "1", "line_key_0": key, field: "0.5",
            "notes_0": "Controlled half-hour persistence regression",
        }, follow_redirects=False)
        assert response.status_code == 303, response.text
        # Inspect before following the redirect; GET/reload must not repair a stale save.
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            adjustment = db.query(model).filter_by(revision_id=rid, line_key=key).one()
            assert getattr(adjustment, attribute) == 0.5
            _, expected, _, _ = calculation(db, rev)
            assert expected["hours"] != before_hours
            assert rev.calculated_hours == pytest.approx(expected["hours"])
            assert rev.calculated_fees == pytest.approx(expected["fees"])
            assert rev.low_hours == pytest.approx(expected["low_hours"])
            assert rev.high_hours == pytest.approx(expected["high_hours"])
            assert rev.duration_months == pytest.approx(expected["duration_months"])
            assert rev.schedule_needs_refresh is True

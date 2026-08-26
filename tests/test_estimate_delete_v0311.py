from fastapi.testclient import TestClient

from app.run import app
from app.assumptions import EstimateAssumption
from app.cip_models import CIPRevisionInput, CIPScopeItem, EstimateProduct
from app.database import SessionLocal
from app.models import (
    AuditEvent,
    CalculationAdjustment,
    Estimate,
    EstimateApplication,
    EstimateCustomApplication,
    EstimateRevision,
)


def login(client):
    response = client.post(
        "/login",
        data={"username": "aDmIn", "password": "TestPass123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def create_estimate(client, product_type="MEP"):
    response = client.post(
        "/estimates/new",
        data={"product_type": product_type},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[-1])


def test_mep_draft_delete_removes_estimate_and_associated_details():
    with TestClient(app) as client:
        login(client)
        rid = create_estimate(client, "MEP")
        page = client.get(f"/estimate/{rid}")
        assert page.status_code == 200
        assert "Delete Estimate" in page.text
        assert "This cannot be undone" in page.text

        assert client.post(f"/estimate/{rid}/assumptions").status_code == 200
        adjustment = client.post(
            f"/estimate/{rid}/calculations",
            data={
                "line_count": "1",
                "line_key_0": "PLAN_KICKOFF",
                "adjust_0": "0.5",
                "notes_0": "Draft estimate deletion regression",
            },
            follow_redirects=False,
        )
        assert adjustment.status_code == 303

        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            estimate_id = rev.estimate_id
            assert db.query(EstimateApplication).filter(EstimateApplication.revision_id == rid).count() > 0
            assert db.query(EstimateCustomApplication).filter(EstimateCustomApplication.revision_id == rid).count() > 0
            assert db.query(EstimateAssumption).filter(EstimateAssumption.revision_id == rid).count() == 1
            assert db.query(CalculationAdjustment).filter(CalculationAdjustment.revision_id == rid).count() == 1
            assert db.query(AuditEvent).filter(AuditEvent.estimate_id == estimate_id).count() > 0

        deleted = client.post(f"/estimate/{rid}/delete", follow_redirects=False)
        assert deleted.status_code == 303
        assert deleted.headers["location"] == "/estimates"

        with SessionLocal() as db:
            assert db.get(EstimateRevision, rid) is None
            assert db.get(Estimate, estimate_id) is None
            assert db.query(EstimateApplication).filter(EstimateApplication.revision_id == rid).count() == 0
            assert db.query(EstimateCustomApplication).filter(EstimateCustomApplication.revision_id == rid).count() == 0
            assert db.query(EstimateAssumption).filter(EstimateAssumption.revision_id == rid).count() == 0
            assert db.query(CalculationAdjustment).filter(CalculationAdjustment.revision_id == rid).count() == 0
            assert db.query(AuditEvent).filter(AuditEvent.estimate_id == estimate_id).count() == 0


def test_cip_draft_delete_removes_product_and_cip_details():
    with TestClient(app) as client:
        login(client)
        rid = create_estimate(client, "CIP")
        page = client.get(f"/estimate/{rid}")
        assert page.status_code == 200
        assert "Delete Estimate" in page.text

        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            estimate_id = rev.estimate_id
            assert db.get(CIPRevisionInput, rid) is not None
            assert db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rid).count() > 0
            assert db.get(EstimateProduct, estimate_id) is not None

        deleted = client.post(f"/estimate/{rid}/delete", follow_redirects=False)
        assert deleted.status_code == 303

        with SessionLocal() as db:
            assert db.get(CIPRevisionInput, rid) is None
            assert db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rid).count() == 0
            assert db.get(EstimateProduct, estimate_id) is None
            assert db.get(EstimateRevision, rid) is None
            assert db.get(Estimate, estimate_id) is None


def test_delete_is_unavailable_and_blocked_after_draft_status():
    with TestClient(app) as client:
        login(client)
        rid = create_estimate(client, "MEP")
        submitted = client.post(f"/estimate/{rid}/status/submit", follow_redirects=False)
        assert submitted.status_code == 303

        page = client.get(f"/estimate/{rid}")
        assert page.status_code == 200
        assert "Delete Estimate" not in page.text

        blocked = client.post(f"/estimate/{rid}/delete", follow_redirects=False)
        assert blocked.status_code == 409
        with SessionLocal() as db:
            assert db.get(EstimateRevision, rid) is not None


def test_new_draft_revision_cannot_delete_existing_approved_history():
    with TestClient(app) as client:
        login(client)
        rid = create_estimate(client, "MEP")
        assert client.post(f"/estimate/{rid}/status/submit", follow_redirects=False).status_code == 303
        assert client.post(f"/estimate/{rid}/status/approve", follow_redirects=False).status_code == 303
        new_revision = client.post(
            f"/estimate/{rid}/new-revision",
            data={"revision_reason": "Create a controlled draft while retaining approved history."},
            follow_redirects=False,
        )
        assert new_revision.status_code == 303
        new_rid = int(new_revision.headers["location"].rsplit("/", 1)[-1])

        page = client.get(f"/estimate/{new_rid}")
        assert page.status_code == 200
        assert "Delete Estimate" not in page.text
        assert client.post(f"/estimate/{new_rid}/delete", follow_redirects=False).status_code == 409

        with SessionLocal() as db:
            assert db.get(EstimateRevision, rid) is not None
            assert db.get(EstimateRevision, new_rid) is not None
            assert db.get(EstimateRevision, rid).estimate_id == db.get(EstimateRevision, new_rid).estimate_id

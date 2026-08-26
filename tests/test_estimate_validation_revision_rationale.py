from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.run import app
from app import main as core
from app import cip_domain
from app.cip_models import CIPRevisionInput
from app.database import SessionLocal
from app.models import AuditEvent, EstimateRevision


def _login(client):
    response = client.post(
        "/login",
        data={"username": "Admin", "password": "TestPass123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _new_estimate(client, product: str) -> int:
    response = client.post(
        "/estimates/new",
        data={"product_type": product},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[-1])


def test_mep_epp_requires_positive_sites_and_on_prem_requires_gateway():
    with TestClient(app) as client:
        _login(client)
        rid = _new_estimate(client, "MEP")
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.epp_install = "Cloud"
            rev.label_sites = 0
            rev.gateway = False
            with pytest.raises(HTTPException) as exc:
                core.validate_estimate_business_rules(db, rev)
            assert exc.value.status_code == 400
            assert "At least one label-printing site" in str(exc.value.detail)

            rev.epp_install = "On Prem"
            rev.label_sites = 1
            rev.gateway = False
            with pytest.raises(HTTPException) as exc:
                core.validate_estimate_business_rules(db, rev)
            assert exc.value.status_code == 400
            assert "Install MEP Gateway must be Yes" in str(exc.value.detail)

            # EPP On Prem is itself an allowed Gateway architecture, even if the
            # older Solution Type metadata did not independently mark Gateway valid.
            rev.gateway = True
            core.validate_estimate_business_rules(db, rev)

            rev.epp_install = "No"
            rev.label_sites = 0
            rev.gateway = False
            core.validate_estimate_business_rules(db, rev)


def test_cip_epp_requires_positive_sites_and_on_prem_requires_gateway():
    with TestClient(app) as client:
        _login(client)
        rid = _new_estimate(client, "CIP")
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            inp = db.get(CIPRevisionInput, rid)
            assert inp is not None

            inp.epp_install = "Cloud"
            inp.label_sites = 0
            inp.gateway = False
            with pytest.raises(HTTPException) as exc:
                cip_domain.validate_cip(db, rev, inp)
            assert "At least one label-printing site" in str(exc.value.detail)

            inp.epp_install = "On Prem"
            inp.label_sites = 1
            inp.gateway = False
            with pytest.raises(HTTPException) as exc:
                cip_domain.validate_cip(db, rev, inp)
            assert "Gateway must be Yes" in str(exc.value.detail)

            inp.gateway = True
            cip_domain.validate_cip(db, rev, inp)


def test_mep_revision_requires_notes_and_displays_them_in_revision_history():
    reason = "Customer added a second deployment site and an additional integration."
    with TestClient(app) as client:
        _login(client)
        rid = _new_estimate(client, "MEP")
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.status = "APPROVED"
            db.commit()

        prompt = client.post(f"/estimate/{rid}/new-revision", follow_redirects=False)
        assert prompt.status_code == 200
        assert "Revision Notes" in prompt.text
        assert "permanent revision history" in prompt.text

        blank = client.post(
            f"/estimate/{rid}/new-revision",
            data={"revision_reason": "   "},
            follow_redirects=False,
        )
        assert blank.status_code == 400
        assert "Revision Notes are required" in blank.text

        created = client.post(
            f"/estimate/{rid}/new-revision",
            data={"revision_reason": reason},
            follow_redirects=False,
        )
        assert created.status_code == 303
        new_rid = int(created.headers["location"].rsplit("/", 1)[-1])

        with SessionLocal() as db:
            new_rev = db.get(EstimateRevision, new_rid)
            assert new_rev.revision_no == 2
            event = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.revision_id == new_rid,
                    AuditEvent.event_type == "REVISION_RATIONALE",
                )
                .one()
            )
            assert event.old_value == "REVISION"
            assert event.reason == reason

        history = client.get(f"/estimate/{new_rid}/revisions")
        assert history.status_code == 200
        assert "Revision Notes" in history.text
        assert reason in history.text
        assert "New revision" in history.text


def test_rebase_rationale_is_distinguished_from_normal_revision():
    reason = "Move this estimate onto the newly approved calculation model."
    with TestClient(app) as client:
        _login(client)
        rid = _new_estimate(client, "MEP")
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.status = "APPROVED"
            db.commit()

        created = client.post(
            f"/estimate/{rid}/new-revision?rebase=true",
            data={"revision_reason": reason},
            follow_redirects=False,
        )
        assert created.status_code == 303
        new_rid = int(created.headers["location"].rsplit("/", 1)[-1])
        with SessionLocal() as db:
            event = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.revision_id == new_rid,
                    AuditEvent.event_type == "REVISION_RATIONALE",
                )
                .one()
            )
            assert event.old_value == "REBASE"
            assert event.reason == reason

        history = client.get(f"/estimate/{new_rid}/revisions")
        assert "Rebased revision" in history.text
        assert reason in history.text


def test_cip_revision_uses_the_same_required_rationale_control():
    reason = "Revise CIP scope following customer review of warehouse requirements."
    with TestClient(app) as client:
        _login(client)
        rid = _new_estimate(client, "CIP")
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.status = "APPROVED"
            db.commit()

        prompt = client.post(f"/estimate/{rid}/new-revision", follow_redirects=False)
        assert prompt.status_code == 200
        assert "Revision Notes" in prompt.text

        created = client.post(
            f"/estimate/{rid}/new-revision",
            data={"revision_reason": reason},
            follow_redirects=False,
        )
        assert created.status_code == 303
        new_rid = int(created.headers["location"].rsplit("/", 1)[-1])
        with SessionLocal() as db:
            assert db.get(CIPRevisionInput, new_rid) is not None
            event = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.revision_id == new_rid,
                    AuditEvent.event_type == "REVISION_RATIONALE",
                )
                .one()
            )
            assert event.reason == reason

        history = client.get(f"/estimate/{new_rid}/revisions")
        assert reason in history.text

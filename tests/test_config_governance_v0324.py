from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.auth import hash_password, normalize_username
from app.cip_domain import active_config_for_product
from app.cip_models import PRODUCT_CIP, PRODUCT_MEP
from app.database import SessionLocal
from app.models import AuditEvent, ConfigItem, ConfigurationVersion, EstimateRevision, User, UserRole
from app.run import app


def _login(client: TestClient, username: str = "Admin", password: str = "TestPass123!") -> None:
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)


def _switch_user(client: TestClient, username: str, password: str) -> None:
    client.post("/logout", follow_redirects=False)
    _login(client, username, password)


def _ensure_user(username: str, password: str, role: str) -> int:
    normalized = normalize_username(username)
    with SessionLocal() as db:
        user = db.query(User).filter(User.username_normalized == normalized).first()
        if not user:
            user = User(
                username=username,
                username_normalized=normalized,
                password_hash=hash_password(password),
                role=role,
                active=True,
            )
            db.add(user)
            db.flush()
        else:
            user.password_hash = hash_password(password)
            user.active = True
        if not db.query(UserRole).filter(UserRole.user_id == user.id, UserRole.role == role).first():
            db.add(UserRole(user_id=user.id, role=role))
        db.commit()
        return user.id


def _version_id(response) -> int:
    query = parse_qs(urlparse(response.headers["location"]).query)
    return int(query["version"][0])


def _create_draft(client: TestClient, product: str = PRODUCT_MEP) -> int:
    response = client.post(
        "/data/version/new",
        data={"product": product},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)
    return _version_id(response)


def _create_estimate(client: TestClient) -> int:
    response = client.post("/estimates/new", follow_redirects=False)
    assert response.status_code == 303, (response.status_code, response.text)
    return int(response.headers["location"].rsplit("/", 1)[-1])


def test_two_person_configuration_approval_and_activation_preserve_estimate_pinning():
    reviewer_id = None
    with TestClient(app) as client:
        _login(client)
        reviewer_id = _ensure_user("ConfigReviewer", "ReviewPass123!", "TOOLS_ADMIN")

        rid = _create_estimate(client)
        with SessionLocal() as db:
            revision = db.get(EstimateRevision, rid)
            old_config_id = revision.config_version_id
            old_hours = revision.calculated_hours

        draft_id = _create_draft(client, PRODUCT_MEP)
        with SessionLocal() as db:
            item = db.query(ConfigItem).filter(
                ConfigItem.config_version_id == draft_id,
                ConfigItem.key == "UNIT_TEST_FACTOR",
            ).one()
            item_id = item.id

        response = client.post(
            f"/data/item/{item_id}",
            data={
                "label": "Unit Testing Factor",
                "value_number": "0.25",
                "value_text": "",
                "description": "Governed regression change",
                "active": "on",
                "reason": "Validate two-person configuration governance",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.post(f"/data/version/{draft_id}/submit", follow_redirects=False)
        assert response.status_code == 303
        with SessionLocal() as db:
            version = db.get(ConfigurationVersion, draft_id)
            submitter_id = version.submitted_by
            assert version.status == "PENDING_REVIEW"
            assert version.approval_status == "PENDING_REVIEW"
            assert submitter_id is not None

        # A preparer cannot review the version, even with the ADMIN role.
        response = client.post(
            f"/data/version/{draft_id}/review",
            data={"action": "approve", "reason": "Self approval should be blocked"},
            follow_redirects=False,
        )
        assert response.status_code == 409

        # Activation is impossible until independent approval evidence exists.
        response = client.post(f"/data/version/{draft_id}/activate", follow_redirects=False)
        assert response.status_code == 409

        _switch_user(client, "ConfigReviewer", "ReviewPass123!")
        response = client.post(
            f"/data/version/{draft_id}/review",
            data={"action": "approve", "reason": "Validated calculation delta and regression scenarios"},
            follow_redirects=False,
        )
        assert response.status_code == 303, (response.status_code, response.text)

        with SessionLocal() as db:
            version = db.get(ConfigurationVersion, draft_id)
            assert version.status == "APPROVED"
            assert version.approval_status == "APPROVED"
            assert version.approved_by == reviewer_id
            assert version.approved_by != version.submitted_by
            assert version.approved_at is not None

        response = client.post(f"/data/version/{draft_id}/activate", follow_redirects=False)
        assert response.status_code == 303, (response.status_code, response.text)

        with SessionLocal() as db:
            version = db.get(ConfigurationVersion, draft_id)
            revision = db.get(EstimateRevision, rid)
            assert version.status == "ACTIVE"
            assert version.approval_status == "ACTIVE"
            assert revision.config_version_id == old_config_id
            assert revision.calculated_hours == old_hours
            assert db.get(ConfigurationVersion, old_config_id).status == "RETIRED"
            events = {
                row.event_type
                for row in db.query(AuditEvent).filter(AuditEvent.config_version_id == draft_id).all()
            }
            assert {
                "CONFIG_VERSION_CREATED",
                "CONFIG_VALUE_CHANGED",
                "CONFIG_VERSION_SUBMITTED",
                "CONFIG_VERSION_APPROVED",
                "CONFIG_VERSION_ACTIVATED",
            }.issubset(events)


def test_rejection_requires_reason_locks_version_and_reopen_returns_to_draft():
    with TestClient(app) as client:
        _login(client)
        reviewer_id = _ensure_user("ConfigRejector", "RejectPass123!", "TOOLS_ADMIN")
        draft_id = _create_draft(client, PRODUCT_MEP)

        assert client.post(f"/data/version/{draft_id}/submit", follow_redirects=False).status_code == 303
        _switch_user(client, "ConfigRejector", "RejectPass123!")

        response = client.post(
            f"/data/version/{draft_id}/review",
            data={"action": "reject", "reason": ""},
            follow_redirects=False,
        )
        assert response.status_code == 400

        response = client.post(
            f"/data/version/{draft_id}/review",
            data={"action": "reject", "reason": "Regression evidence does not reconcile"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        with SessionLocal() as db:
            version = db.get(ConfigurationVersion, draft_id)
            assert version.status == "REJECTED"
            assert version.approval_status == "REJECTED"
            assert version.reviewed_by == reviewer_id
            item = db.query(ConfigItem).filter(ConfigItem.config_version_id == draft_id).first()
            item_id = item.id

        _switch_user(client, "Admin", "TestPass123!")
        response = client.post(
            f"/data/item/{item_id}",
            data={"label": "Locked", "reason": "Should not save"},
            follow_redirects=False,
        )
        assert response.status_code == 409

        response = client.post(
            f"/data/version/{draft_id}/reopen",
            data={"reason": "Address rejection findings and rerun validation"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        with SessionLocal() as db:
            version = db.get(ConfigurationVersion, draft_id)
            assert version.status == "DRAFT"
            assert version.approval_status == "DRAFT"
            assert version.submitted_by is None
            assert version.submitted_at is None
            assert version.reviewed_by is None
            assert version.reviewed_at is None
            assert version.approved_by is None
            assert version.approved_at is None
            assert db.query(AuditEvent).filter(
                AuditEvent.config_version_id == draft_id,
                AuditEvent.event_type == "CONFIG_VERSION_REJECTED",
                AuditEvent.reason == "Regression evidence does not reconcile",
            ).count() == 1
            assert db.query(AuditEvent).filter(
                AuditEvent.config_version_id == draft_id,
                AuditEvent.event_type == "CONFIG_VERSION_REOPENED",
            ).count() == 1


def test_cip_activation_retires_only_cip_active_configuration():
    with TestClient(app) as client:
        _login(client)
        _ensure_user("CIPConfigReviewer", "CIPReview123!", "TOOLS_ADMIN")
        with SessionLocal() as db:
            mep_active_id = active_config_for_product(db, PRODUCT_MEP).id
            cip_active_id = active_config_for_product(db, PRODUCT_CIP).id

        draft_id = _create_draft(client, PRODUCT_CIP)
        assert client.post(f"/data/version/{draft_id}/submit", follow_redirects=False).status_code == 303
        _switch_user(client, "CIPConfigReviewer", "CIPReview123!")
        assert client.post(
            f"/data/version/{draft_id}/review",
            data={"action": "approve", "reason": "CIP catalog regression validated"},
            follow_redirects=False,
        ).status_code == 303
        assert client.post(f"/data/version/{draft_id}/activate", follow_redirects=False).status_code == 303

        with SessionLocal() as db:
            assert active_config_for_product(db, PRODUCT_MEP).id == mep_active_id
            assert active_config_for_product(db, PRODUCT_CIP).id == draft_id
            assert db.get(ConfigurationVersion, cip_active_id).status == "RETIRED"


def test_calculation_data_page_exposes_governance_state_and_controls():
    with TestClient(app) as client:
        _login(client)
        draft_id = _create_draft(client, PRODUCT_MEP)
        page = client.get(f"/data?product=MEP&version={draft_id}")
        assert page.status_code == 200
        assert "Configuration Governance" in page.text
        assert "Submit for Review" in page.text
        assert "separation of duties" in page.text.lower()

from __future__ import annotations

from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.models import User, UserRole


def _login_admin(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "Admin", "password": "TestPass123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)


def test_user_role_update_retains_existing_rows_when_adding_tools_admin():
    with TestClient(app) as client:
        _login_admin(client)

        created = client.post(
            "/admin/users/create",
            data={
                "username": "RoleUpdateRegression",
                "email": "role-update-regression@example.com",
                "password": "RoleUpdatePass123!",
                "active": "1",
                "roles": ["ADMIN", "ESTIMATOR", "REVIEWER"],
            },
            follow_redirects=False,
        )
        assert created.status_code == 303, (created.status_code, created.text)

        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "RoleUpdateRegression").one()
            user_id = user.id
            before = {row.role: row.id for row in user.roles}
            assert set(before) == {"ADMIN", "ESTIMATOR", "REVIEWER"}

        updated = client.post(
            f"/admin/users/{user_id}/update",
            data={
                "email": "role-update-regression@example.com",
                "active": "1",
                "roles": ["ADMIN", "TOOLS_ADMIN", "ESTIMATOR", "REVIEWER"],
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303, (updated.status_code, updated.text)

        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user is not None
            after_add = {row.role: row.id for row in user.roles}
            assert set(after_add) == {"ADMIN", "TOOLS_ADMIN", "ESTIMATOR", "REVIEWER"}
            assert after_add["ADMIN"] == before["ADMIN"]
            assert after_add["ESTIMATOR"] == before["ESTIMATOR"]
            assert after_add["REVIEWER"] == before["REVIEWER"]
            assert user.role == "ADMIN"
            assert db.query(UserRole).filter(UserRole.user_id == user_id).count() == 4

        removed = client.post(
            f"/admin/users/{user_id}/update",
            data={
                "email": "role-update-regression@example.com",
                "active": "1",
                "roles": ["ADMIN", "TOOLS_ADMIN", "ESTIMATOR"],
            },
            follow_redirects=False,
        )
        assert removed.status_code == 303, (removed.status_code, removed.text)

        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user is not None
            after_remove = {row.role: row.id for row in user.roles}
            assert set(after_remove) == {"ADMIN", "TOOLS_ADMIN", "ESTIMATOR"}
            assert after_remove["ADMIN"] == before["ADMIN"]
            assert after_remove["ESTIMATOR"] == before["ESTIMATOR"]
            assert "REVIEWER" not in after_remove
            assert db.query(UserRole).filter(UserRole.user_id == user_id).count() == 3

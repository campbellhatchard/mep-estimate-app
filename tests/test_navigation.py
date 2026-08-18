from fastapi.testclient import TestClient

from app.run import app


def test_admin_navigation_keeps_management_screens_accessible():
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "Admin", "password": "TestPass123!"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        page = client.get("/estimates")
        assert page.status_code == 200
        html = page.text

        # Desktop and responsive navigation must both expose these controls.
        assert html.count('href="/data"') >= 2
        assert html.count('href="/admin/users"') >= 2
        assert 'class="mobile-nav-menu"' in html

        # The underlying management screens must remain directly reachable.
        assert client.get("/data").status_code == 200
        assert client.get("/admin/users").status_code == 200

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import ConfigurationVersion
from app.run import app


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "Admin", "password": "TestPass123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)


def _version_id(response) -> int:
    query = parse_qs(urlparse(response.headers["location"]).query)
    return int(query["version"][0])


def test_multiple_calculation_data_drafts_created_in_same_minute_have_unique_names():
    with TestClient(app) as client:
        _login(client)
        first = client.post(
            "/data/version/new",
            data={"product": "MEP"},
            follow_redirects=False,
        )
        second = client.post(
            "/data/version/new",
            data={"product": "MEP"},
            follow_redirects=False,
        )

        assert first.status_code == 303, (first.status_code, first.text)
        assert second.status_code == 303, (second.status_code, second.text)

        first_id = _version_id(first)
        second_id = _version_id(second)
        assert first_id != second_id

        with SessionLocal() as db:
            first_version = db.get(ConfigurationVersion, first_id)
            second_version = db.get(ConfigurationVersion, second_id)
            assert first_version is not None
            assert second_version is not None
            assert first_version.name != second_version.name
            assert first_version.name.startswith("MEP Estimate Model ")
            assert second_version.name.startswith("MEP Estimate Model ")
            assert first_version.status == "DRAFT"
            assert second_version.status == "DRAFT"

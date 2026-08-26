from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.run import app
from app import main as core
from app import cip_routes_detail
from app.database import SessionLocal
from app.models import AuditEvent, ConfigItem, ConfigurationVersion, EstimateRevision, User
from app.sow_models import SOWTemplateVersion, SOW_TEMPLATE_MEP_NET_NEW


def _login(client, username="Admin", password="TestPass123!"):
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)


def _new_estimate(client, product: str) -> int:
    response = client.post(
        "/estimates/new",
        data={"product_type": product},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)
    return int(response.headers["location"].rstrip("/").rsplit("/", 1)[-1])


def test_tools_admin_can_administer_data_and_templates_but_not_users():
    with TestClient(app) as client:
        _login(client)
        created = client.post(
            "/admin/users/create",
            data={
                "username": "ToolsAdminRegression",
                "email": "tools-admin-regression@example.com",
                "password": "ToolsAdminPass123!",
                "active": "1",
                "roles": "TOOLS_ADMIN",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303, (created.status_code, created.text)

        with SessionLocal() as db:
            tools_user = db.query(User).filter(User.username == "ToolsAdminRegression").one()
            assert tools_user.has_role("TOOLS_ADMIN")
            assert not tools_user.has_role("ADMIN")
            tools_user_id = tools_user.id
            source_template = (
                db.query(SOWTemplateVersion)
                .filter(
                    SOWTemplateVersion.template_key == SOW_TEMPLATE_MEP_NET_NEW,
                    SOWTemplateVersion.status == "ACTIVE",
                )
                .order_by(SOWTemplateVersion.version_no.desc())
                .first()
            )
            assert source_template is not None
            source_template_id = source_template.id
            source_template_content = bytes(source_template.content)

        client.post("/logout", follow_redirects=False)
        _login(client, "ToolsAdminRegression", "ToolsAdminPass123!")

        # User administration remains ADMIN-only.
        users = client.get("/admin/users")
        assert users.status_code == 403

        data_page = client.get("/data?product=MEP")
        assert data_page.status_code == 200
        assert "Changing a Calculation Data Element" in data_page.text
        assert "Create MEP Draft from Active" in data_page.text

        new_version = client.post(
            "/data/version/new",
            data={"product": "MEP"},
            follow_redirects=False,
        )
        assert new_version.status_code == 303, (new_version.status_code, new_version.text)
        query = parse_qs(urlparse(new_version.headers["location"]).query)
        version_id = int(query["version"][0])

        with SessionLocal() as db:
            version = db.get(ConfigurationVersion, version_id)
            assert version is not None and version.status == "DRAFT"
            item = (
                db.query(ConfigItem)
                .filter(
                    ConfigItem.config_version_id == version_id,
                    ConfigItem.value_number.is_not(None),
                )
                .order_by(ConfigItem.id)
                .first()
            )
            assert item is not None
            item_id = item.id
            old_value = float(item.value_number)
            item_label = item.label
            item_text = item.value_text or ""
            item_description = item.description or ""

        changed_value = old_value + 0.25
        updated = client.post(
            f"/data/item/{item_id}",
            data={
                "label": item_label,
                "value_number": str(changed_value),
                "value_text": item_text,
                "description": item_description,
                "active": "on",
                "reason": "Regression test controlled Tools Admin change",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303, (updated.status_code, updated.text)
        with SessionLocal() as db:
            item = db.get(ConfigItem, item_id)
            assert float(item.value_number) == changed_value
            event = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.config_version_id == version_id,
                    AuditEvent.event_type == "CONFIG_VALUE_CHANGED",
                    AuditEvent.user_id == tools_user_id,
                )
                .order_by(AuditEvent.id.desc())
                .first()
            )
            assert event is not None
            assert "Regression test controlled Tools Admin change" in (event.reason or "")

        sow_admin = client.get("/admin/sow-templates")
        assert sow_admin.status_code == 200
        assert "Upload New Template Version" in sow_admin.text
        assert sow_admin.text.count("Change Reason") >= 5
        assert "grid-template-columns:repeat(2" in sow_admin.text

        downloaded = client.get(f"/admin/sow-templates/{source_template_id}/download")
        assert downloaded.status_code == 200
        assert downloaded.content == source_template_content

        uploaded = client.post(
            "/admin/sow-templates/upload",
            data={
                "template_key": SOW_TEMPLATE_MEP_NET_NEW,
                "change_reason": "Tools Admin controlled template regression copy",
            },
            files={
                "file": (
                    "MEP_Tools_Admin_Regression.docx",
                    source_template_content,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            follow_redirects=False,
        )
        assert uploaded.status_code == 303, (uploaded.status_code, uploaded.text)
        with SessionLocal() as db:
            draft = (
                db.query(SOWTemplateVersion)
                .filter(
                    SOWTemplateVersion.template_key == SOW_TEMPLATE_MEP_NET_NEW,
                    SOWTemplateVersion.status == "DRAFT",
                    SOWTemplateVersion.created_by == tools_user_id,
                )
                .order_by(SOWTemplateVersion.version_no.desc())
                .first()
            )
            assert draft is not None
            assert draft.change_reason == "Tools Admin controlled template regression copy"


def test_every_mep_and_cip_calculation_line_has_explain_evidence():
    with TestClient(app) as client:
        _login(client)

        mep_rid = _new_estimate(client, "MEP")
        with SessionLocal() as db:
            mep_rev = db.get(EstimateRevision, mep_rid)
            lines, _, _, _ = core.calculation(db, mep_rev)
            assert lines
            assert all((line.trace or "").strip() for line in lines)
            gateway = next(line for line in lines if line.key == "PLAN_GATEWAY")
            assert "GATEWAY_INSTALL_HOURS" in gateway.trace
            assert f"Configuration {mep_rev.config_version_id}" in gateway.trace
            assert "Standard Adjust" in gateway.trace

        mep_page = client.get(f"/estimate/{mep_rid}/calculations")
        assert mep_page.status_code == 200
        assert "Explain" in mep_page.text
        assert "Calculation Data:" in mep_page.text

        cip_rid = _new_estimate(client, "CIP")
        with SessionLocal() as db:
            cip_rev = db.get(EstimateRevision, cip_rid)
            lines, _, _, _ = cip_routes_detail.cip_calculation(db, cip_rev)
            assert lines
            assert all((line.trace or "").strip() for line in lines)
            gateway = next(line for line in lines if line.key == "PLAN_GATEWAY")
            assert "GATEWAY_INSTALL_HOURS" in gateway.trace
            assert f"Configuration {cip_rev.config_version_id}" in gateway.trace
            assert "Plan Hours Not Billable" in gateway.trace

        cip_page = client.get(f"/estimate/{cip_rid}/calculations")
        assert cip_page.status_code == 200
        assert "<th>Rule</th>" in cip_page.text
        assert "Explain" in cip_page.text
        assert "Calculation Data:" in cip_page.text

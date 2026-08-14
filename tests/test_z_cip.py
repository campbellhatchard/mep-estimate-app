import re

from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.models import EstimateRevision, ConfigurationVersion
from app.cip_models import CIPRevisionInput, CIPScopeItem, ConfigurationProduct, EstimateProduct


def login(client):
    response = client.post("/login", data={"username": "aDmIn", "password": "TestPass123!"}, follow_redirects=False)
    assert response.status_code == 303


def create_cip(client):
    response = client.post("/estimates/new", data={"product_type": "CIP"}, follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[-1])


def create_mep(client):
    # Backward-compatible POST without product_type remains MEP. The visible UI always
    # asks the user to choose MEP or CIP first.
    response = client.post("/estimates/new", follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[-1])


def test_product_chooser_and_cip_default_workbook_golden_scenario():
    with TestClient(app) as client:
        login(client)
        chooser = client.get("/estimates/new")
        assert chooser.status_code == 200
        assert "Mobile Enterprise Platform" in chooser.text
        assert "Cloud Inventory Platform" in chooser.text

        rid = create_cip(client)
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            product = db.get(EstimateProduct, rev.estimate_id)
            inp = db.get(CIPRevisionInput, rid)
            assert product.product_type == "CIP"
            assert re.fullmatch(r"\d{9}", rev.estimate.estimate_number)
            assert inp.release_key == "RELEASE_26_2"
            # Approved workbook default: 239 Investment Hours at $250/hour, 1.12 months.
            assert rev.calculated_hours == 239
            assert rev.calculated_fees == 59750
            assert rev.duration_months == 1.12

        for path in [f"/estimate/{rid}", f"/estimate/{rid}/detail", f"/estimate/{rid}/calculations", f"/estimate/{rid}/schedule", f"/estimate/{rid}/audit"]:
            assert client.get(path).status_code == 200

        assert client.get(f"/estimate/{rid}/pdf").content.startswith(b"%PDF")
        jira = client.get(f"/estimate/{rid}/jira.csv")
        assert jira.status_code == 200
        assert "Original estimate (in hours)" in jira.text
        assert "Original estimate (in seconds)" not in jira.text


def test_mep_and_cip_share_one_monthly_number_sequence():
    with TestClient(app) as client:
        login(client)
        mep_rid = create_mep(client)
        cip_rid = create_cip(client)
        with SessionLocal() as db:
            mep_number = db.get(EstimateRevision, mep_rid).estimate.estimate_number
            cip_number = db.get(EstimateRevision, cip_rid).estimate.estimate_number
        assert mep_number[:6] == cip_number[:6]
        assert int(cip_number[-3:]) == int(mep_number[-3:]) + 1


def test_cip_release_change_resets_release_dependent_scope():
    with TestClient(app) as client:
        login(client)
        rid = create_cip(client)
        with SessionLocal() as db:
            first = db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rid, CIPScopeItem.category == "DESKTOP").order_by(CIPScopeItem.sort_order).first()
            first.config_type = "Baseline"
            db.commit()

        response = client.post(f"/estimate/{rid}", data={"release_key": "RELEASE_25_3"}, follow_redirects=False)
        assert response.status_code == 303
        with SessionLocal() as db:
            inp = db.get(CIPRevisionInput, rid)
            rows = db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rid, CIPScopeItem.category.in_(["DESKTOP", "MOBILE", "INTEGRATION"])).all()
            assert inp.release_key == "RELEASE_25_3"
            assert rows
            assert all(row.config_type == "No Config" for row in rows)


def test_cip_testing_adjustment_requires_reason_and_is_auditable():
    with TestClient(app) as client:
        login(client)
        rid = create_cip(client)
        with SessionLocal() as db:
            row = db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rid, CIPScopeItem.category == "DESKTOP").order_by(CIPScopeItem.sort_order).first()
            scope_id = row.id

        bad = client.post(f"/estimate/{rid}/detail", data={"line_count":"1","scope_id_0":str(scope_id),"added_0":"0","adjustment_notes_0":"","test_adjust_0":"2","test_notes_0":"","description_0":"","app_count_0":"0","integration_added_0":"0"})
        assert bad.status_code == 400

        good = client.post(f"/estimate/{rid}/detail", data={"line_count":"1","scope_id_0":str(scope_id),"added_0":"0","adjustment_notes_0":"","test_adjust_0":"2","test_notes_0":"Additional customer validation","description_0":"","app_count_0":"0","integration_added_0":"0"}, follow_redirects=False)
        assert good.status_code == 303


def test_mep_and_cip_active_configuration_are_independent():
    with TestClient(app) as client:
        login(client)
        create_cip(client)
        with SessionLocal() as db:
            active = db.query(ConfigurationVersion).filter(ConfigurationVersion.status == "ACTIVE").all()
            products = []
            for version in active:
                mapping = db.get(ConfigurationProduct, version.id)
                products.append(mapping.product_type if mapping else "MEP")
            assert "MEP" in products
            assert "CIP" in products

        data = client.get("/data?product=CIP")
        assert data.status_code == 200
        assert "CIP Calculation Data" in data.text
        assert "CIP Release" in data.text

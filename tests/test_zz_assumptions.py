from fastapi.testclient import TestClient

from app.run import app
from app.assumptions import EstimateAssumption
from app.cip_models import CIPRevisionInput
from app.database import SessionLocal


def login(client):
    response = client.post('/login', data={'username': 'aDmIn', 'password': 'TestPass123!'}, follow_redirects=False)
    assert response.status_code == 303


def create_mep(client):
    response = client.post('/estimates/new', follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers['location'].rsplit('/', 1)[-1])


def create_cip(client):
    response = client.post('/estimates/new', data={'product_type': 'CIP'}, follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers['location'].rsplit('/', 1)[-1])


def approve(client, rid):
    assert client.post(f'/estimate/{rid}/status/submit', follow_redirects=False).status_code == 303
    assert client.post(f'/estimate/{rid}/status/approve', follow_redirects=False).status_code == 303


def test_assumptions_are_revision_scoped_locked_and_carried_forward():
    with TestClient(app) as client:
        login(client)
        rid1 = create_mep(client)
        added = client.post(f'/estimate/{rid1}/assumptions')
        assert added.status_code == 200
        aid = added.json()['id']
        updated = client.post(
            f'/estimate/{rid1}/assumptions/{aid}',
            data={'text': 'Estimate assumes customer provides VPN access and test data.'},
        )
        assert updated.status_code == 200
        assert 'VPN access' in client.get(f'/estimate/{rid1}').text

        approve(client, rid1)
        assert client.post(f'/estimate/{rid1}/assumptions').status_code == 409
        assert client.post(f'/estimate/{rid1}/assumptions/{aid}', data={'text': 'Changed'}).status_code == 409

        response = client.post(
            f'/estimate/{rid1}/new-revision',
            data={'revision_reason': 'Revise approved estimate while carrying forward current assumptions.'},
            follow_redirects=False,
        )
        assert response.status_code == 303
        rid2 = int(response.headers['location'].rsplit('/', 1)[-1])
        with SessionLocal() as db:
            rows = db.query(EstimateAssumption).filter(EstimateAssumption.revision_id == rid2).all()
            assert len(rows) == 1
            assert rows[0].text == 'Estimate assumes customer provides VPN access and test data.'
            copied_id = rows[0].id

        deleted = client.post(f'/estimate/{rid2}/assumptions/{copied_id}/delete')
        assert deleted.status_code == 200
        with SessionLocal() as db:
            assert db.query(EstimateAssumption).filter(EstimateAssumption.revision_id == rid2).count() == 0
            assert db.query(EstimateAssumption).filter(EstimateAssumption.revision_id == rid1).count() == 1


def test_cip_range_factors_accept_percent_values_and_preserve_legacy_decimals():
    with TestClient(app) as client:
        login(client)
        rid = create_cip(client)
        response = client.post(
            f'/estimate/{rid}',
            data={'low_factor': '12.5', 'high_factor': '30', 'range_values_are_percent': '1'},
            follow_redirects=False,
        )
        assert response.status_code == 303
        with SessionLocal() as db:
            inp = db.get(CIPRevisionInput, rid)
            assert inp.low_factor == 0.125
            assert inp.high_factor == 0.30

        response = client.post(
            f'/estimate/{rid}',
            data={'low_factor': '0.10', 'high_factor': '0.25'},
            follow_redirects=False,
        )
        assert response.status_code == 303
        with SessionLocal() as db:
            inp = db.get(CIPRevisionInput, rid)
            assert inp.low_factor == 0.10
            assert inp.high_factor == 0.25

        script = client.get('/static/cip_range_percent.js')
        assert script.status_code == 200
        assert "range_values_are_percent" in script.text
        assert "Low Factor (%)" in script.text
        assert "High Factor (%)" in script.text

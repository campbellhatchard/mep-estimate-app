from pathlib import Path

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Estimate, EstimateRevision
from app.run import app


def login(client: TestClient) -> None:
    response = client.post(
        '/login',
        data={'username': 'aDmIn', 'password': 'TestPass123!'},
        follow_redirects=False,
    )
    assert response.status_code == 303


def create_mep(client: TestClient) -> int:
    response = client.post('/estimates/new', data={'product_type': 'MEP'}, follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers['location'].rsplit('/', 1)[-1])


def test_error_modal_uses_form_action_unless_submitter_explicitly_overrides_it():
    js = Path('app/static/error_modal.js').read_text(encoding='utf-8')
    base = Path('app/templates/base.html').read_text(encoding='utf-8')

    assert "submitter?.hasAttribute('formaction')" in js
    assert "submitter?.hasAttribute('formmethod')" in js
    assert ": (form.action || window.location.href)" in js
    assert 'action="/estimate/{{rev.id}}/delete"' in base


def test_partial_invalid_draft_can_be_deleted_without_estimate_validation():
    with TestClient(app) as client:
        login(client)
        rid = create_mep(client)

        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            estimate_id = rev.estimate_id
            # Deliberately create values that would fail normal Estimate validation.
            rev.epp_install = 'No'
            rev.epp_integration = 'Existing Environment'
            rev.go_live_type = 'Remote All'
            rev.go_live_sites = 0
            db.commit()

        response = client.post(f'/estimate/{rid}/delete', follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == '/estimates'

        with SessionLocal() as db:
            assert db.get(EstimateRevision, rid) is None
            assert db.get(Estimate, estimate_id) is None


def test_release_version_is_v0314():
    assert app.version == '0.3.14'

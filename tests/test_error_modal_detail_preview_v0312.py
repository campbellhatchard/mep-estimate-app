from pathlib import Path

from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.models import DetailAdjustment, EstimateApplication, EstimateRevision
from app.services.calculation_v101 import calculation as mep_calculation


def login(client):
    response = client.post('/login', data={'username': 'aDmIn', 'password': 'TestPass123!'}, follow_redirects=False)
    assert response.status_code == 303


def create_mep(client):
    response = client.post('/estimates/new', data={'product_type': 'MEP'}, follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers['location'].rsplit('/', 1)[-1])


def test_shared_error_modal_is_loaded_with_ok_action_and_post_interception():
    base = Path('app/templates/base.html').read_text(encoding='utf-8')
    js = Path('app/static/error_modal.js').read_text(encoding='utf-8')
    css = Path('app/static/error_modal.css').read_text(encoding='utf-8')

    assert '/static/error_modal.css' in base
    assert '/static/error_modal.js' in base
    assert 'id="ciErrorModal"' in base
    assert 'id="ciErrorOk"' in base
    assert '>OK<' in base
    assert "event.defaultPrevented" in js
    assert "window.CIErrorModal" in js
    assert "response.ok" in js
    assert '.ci-error-modal' in css


def test_mep_detail_preview_updates_mod_hours_and_dependent_values_without_persisting():
    with TestClient(app) as client:
        login(client)
        rid = create_mep(client)

        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            app_row = (
                db.query(EstimateApplication)
                .filter(EstimateApplication.revision_id == rid, EstimateApplication.kind == 'APPLICATION')
                .order_by(EstimateApplication.sort_order)
                .first()
            )
            assert app_row is not None
            app_row.config_type = 'Mod Required'
            db.commit()

            _, before_summary, details, _ = mep_calculation(db, rev)
            target = next(line for line in details if line.section == 'Baseline Applications' and line.key == f'APP:{app_row.catalog_key}')
            base_hours = target.base_hours
            original_override = rev.unit_test_factor_override
            original_adjustments = db.query(DetailAdjustment).filter(DetailAdjustment.revision_id == rid).count()

        response = client.post(
            f'/estimate/{rid}/detail/preview',
            data={
                'line_count': '1',
                'line_key_0': target.key,
                'description_0': target.definition,
                'mod_0': '2.5',
                'notes_0': '',
                'unit_test_factor_override': '',
            },
        )
        assert response.status_code == 200
        payload = response.json()
        row = next(item for item in payload['rows'] if item['key'] == target.key)
        assert row['mod'] == 2.5
        assert row['dev'] == base_hours + 2.5
        assert row['total'] == row['dev'] + row['unit']
        assert payload['sections']['Baseline Applications']['dev'] >= row['dev']
        assert payload['estimate']['hours'] != before_summary['hours']

        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            assert rev.unit_test_factor_override == original_override
            assert db.query(DetailAdjustment).filter(DetailAdjustment.revision_id == rid).count() == original_adjustments


def test_detail_template_and_ui_have_live_recalculation_hooks():
    template = Path('app/templates/detail.html').read_text(encoding='utf-8')
    js = Path('app/static/detail_preview.js').read_text(encoding='utf-8')

    assert 'data-detail-line' in template
    assert 'dev-subtotal' in template
    assert 'unit-testing' in template
    assert 'line-total' in template
    assert 'data-detail-section' in template
    assert "input[name^=\"mod_\"]" in js
    assert "window.location.pathname}/preview" in js
    assert "setTimeout(preview, 120)" in js

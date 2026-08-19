from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.models import CalculationAdjustment, EstimateRevision
from app.precision_runtime import format_hours
from app.services.calculation import calculation as legacy_calculation
from app.services.calculation_v101 import calculation as calculation_v101


def login(client):
    response = client.post('/login', data={'username': 'Admin', 'password': 'TestPass123!'}, follow_redirects=False)
    assert response.status_code == 303


def create_revision(client):
    response = client.post('/estimates/new', follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers['location'].rsplit('/', 1)[-1])


def create_cip_revision(client):
    response = client.post('/estimates/new', data={'product_type': 'CIP'}, follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers['location'].rsplit('/', 1)[-1])


def test_mep_standard_adjust_preserves_half_hour_precision():
    with TestClient(app) as client:
        login(client)
        rid = create_revision(client)
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.project_type = 'MEP On Prem'
            db.add(CalculationAdjustment(revision_id=rid, line_key='PLAN_ADW', adjust_hours=0.5, notes='Precision regression'))
            db.flush()
            lines, summary, _, _ = calculation_v101(db, rev)
            adw = next(row for row in lines if row.key == 'PLAN_ADW')
            assert adw.standard_hours == 8
            assert adw.extended_hours == 8.5
            assert summary['hours'] * 4 == round(summary['hours'] * 4)

            row = db.query(CalculationAdjustment).filter_by(revision_id=rid, line_key='PLAN_ADW').one()
            row.adjust_hours = -0.5
            db.flush()
            lines, _, _, _ = calculation_v101(db, rev)
            adw = next(row for row in lines if row.key == 'PLAN_ADW')
            assert adw.standard_hours == 8
            assert adw.extended_hours == 7.5


def test_locked_v100_revision_keeps_historical_rounding():
    with TestClient(app) as client:
        login(client)
        rid = create_revision(client)
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.project_type = 'MEP On Prem'
            rev.status = 'APPROVED'
            rev.engine_version = '1.0.0'
            db.add(CalculationAdjustment(revision_id=rid, line_key='PLAN_ADW', adjust_hours=0.5, notes='Historical value'))
            db.flush()
            new_lines, _, _, _ = calculation_v101(db, rev)
            old_lines, _, _, _ = legacy_calculation(db, rev)
            assert next(row for row in new_lines if row.key == 'PLAN_ADW').extended_hours == next(row for row in old_lines if row.key == 'PLAN_ADW').extended_hours


def test_calculation_preview_updates_without_saving():
    with TestClient(app) as client:
        login(client)
        rid = create_revision(client)
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.project_type = 'MEP On Prem'
            db.commit()
        response = client.post(f'/estimate/{rid}/calculations/preview', data={
            'line_count': '1',
            'line_key_0': 'PLAN_ADW',
            'adjust_0': '0.5',
        })
        assert response.status_code == 200
        row = next(item for item in response.json()['rows'] if item['key'] == 'PLAN_ADW')
        assert row['standard'] == 8
        assert row['extended'] == 8.5
        with SessionLocal() as db:
            assert db.query(CalculationAdjustment).filter_by(revision_id=rid, line_key='PLAN_ADW').count() == 0


def test_cip_project_management_adjustment_is_added_after_formula_rounding():
    with TestClient(app) as client:
        login(client)
        rid = create_cip_revision(client)
        base = client.post(f'/estimate/{rid}/calculations/preview', data={
            'line_count': '1', 'line_key_0': 'PLAN_PM', 'phase_0': 'Plan', 'adjust_0': '0'
        })
        adjusted = client.post(f'/estimate/{rid}/calculations/preview', data={
            'line_count': '1', 'line_key_0': 'PLAN_PM', 'phase_0': 'Plan', 'adjust_0': '0.5'
        })
        assert base.status_code == adjusted.status_code == 200
        base_row = next(item for item in base.json()['rows'] if item['key'] == 'PLAN_PM')
        adjusted_row = next(item for item in adjusted.json()['rows'] if item['key'] == 'PLAN_PM')
        assert adjusted_row['investment'] == base_row['investment'] + 0.5
        with SessionLocal() as db:
            assert db.query(CalculationAdjustment).filter_by(revision_id=rid, line_key='PLAN_PM').count() == 0


def test_hour_display_uses_only_required_decimal_places():
    assert format_hours(8) == '8'
    assert format_hours(8.0) == '8'
    assert format_hours(8.5) == '8.5'
    assert format_hours(8.25) == '8.25'
    assert format_hours(8.50) == '8.5'
    assert format_hours(8.256) == '8.26'

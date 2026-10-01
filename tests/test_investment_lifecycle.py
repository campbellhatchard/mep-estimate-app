"""Funding, precision and authoritative totals must survive approval and revision."""
import re
from html import unescape

import pytest
from fastapi.testclient import TestClient

from app import main as core, cip_routes_detail
from app.cip_models import CIPNonBillableAllocation
from app.database import SessionLocal
from app.models import CalculationAdjustment, EstimateRevision
from app.run import app
from app.services.cip_calculation_v101 import calculation as cip_v101
from app.services.cip_phase_engine import calculation as cip_legacy


def create(client, product):
    assert client.post('/login', data={'username': 'Admin', 'password': 'TestPass123!'}, follow_redirects=False).status_code == 303
    result = client.post('/estimates/new', data={'product_type': product}, follow_redirects=False)
    assert result.status_code == 303
    return int(result.headers['location'].rsplit('/', 1)[-1])


def approve(client, rid):
    for action in ('submit', 'approve'):
        assert client.post(f'/estimate/{rid}/status/{action}', follow_redirects=False).status_code == 303


@pytest.mark.parametrize('status', ['APPROVED', 'FINAL', 'SUPERSEDED'])
def test_cip_funding_precision_is_stable_when_locked(status):
    with TestClient(app) as client:
        rid = create(client, 'CIP')
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            db.add(CalculationAdjustment(revision_id=rid, line_key='PLAN_PM', adjust_hours=0.5, notes='Fractional management effort'))
            db.add(CIPNonBillableAllocation(revision_id=rid, line_key='PLAN_KICKOFF', hours=4, notes='Approved funding'))
            db.flush()
            before_lines, before, *_ = cip_routes_detail.cip_recalculate_and_store(db, rev)
            before_pm = next(line.task_hours for line in before_lines if line.key == 'PLAN_PM')
            rev.status = status
            db.commit()
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            lines, after, *_ = cip_routes_detail.cip_calculation(db, rev)
            assert next(line.task_hours for line in lines if line.key == 'PLAN_PM') == before_pm
            assert after == before
            assert rev.calculated_hours == after['billable_hours']
            assert rev.calculated_fees == after['fees']


@pytest.mark.parametrize('version, oracle', [('CIP-1.0.0', cip_legacy), ('CIP-1.0.1', cip_v101)])
def test_cip_prior_locked_engines_keep_original_results(version, oracle):
    with TestClient(app) as client:
        rid = create(client, 'CIP')
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.engine_version = version
            rev.status = 'APPROVED'
            db.add(CalculationAdjustment(revision_id=rid, line_key='PLAN_PM', adjust_hours=0.5, notes='Historical adjustment'))
            db.add(CIPNonBillableAllocation(revision_id=rid, line_key='PLAN_KICKOFF', hours=4, notes='Historical additive hours'))
            db.flush()
            expected = oracle(db, rev)[1]
            assert cip_routes_detail.cip_calculation(db, rev)[1] == expected
            assert rev.engine_version == version


@pytest.mark.parametrize('product, engine', [('MEP', '1.0.1'), ('CIP', 'CIP-1.0.2')])
@pytest.mark.parametrize('rebase', [False, True], ids=['revision', 'rebase'])
def test_revision_copy_persists_authoritative_adjusted_totals(product, engine, rebase):
    with TestClient(app) as client:
        rid = create(client, product)
        calculate = core.calculation if product == 'MEP' else cip_routes_detail.cip_calculation
        recalculate = core.recalculate_and_store if product == 'MEP' else cip_routes_detail.cip_recalculate_and_store
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            db.add(CalculationAdjustment(revision_id=rid, line_key='PLAN_KICKOFF', adjust_hours=0.5, notes='Copied fractional adjustment'))
            if product == 'CIP':
                db.add(CIPNonBillableAllocation(revision_id=rid, line_key='PLAN_KICKOFF', hours=4, notes='Copied funding allocation'))
            db.flush()
            _, expected, *_ = recalculate(db, rev)
            db.commit()
        approve(client, rid)
        response = client.post(f'/estimate/{rid}/new-revision?rebase={str(rebase).lower()}', data={'revision_reason': 'Controlled copy preserving effort and funding'}, follow_redirects=False)
        assert response.status_code == 303, response.text
        new_rid = int(response.headers['location'].rsplit('/', 1)[-1])
        assert new_rid != rid
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, new_rid)
            assert rev.engine_version == engine
            _, actual, *_ = calculate(db, rev)
            assert actual['hours'] == expected['hours']
            assert rev.calculated_hours == expected['hours']
            assert rev.calculated_fees == expected['fees']
            source = db.get(EstimateRevision, rid)
            assert source.status == 'APPROVED'
            assert source.engine_version == engine
            assert source.calculated_hours == expected['hours']


def test_cip_nonplan_investment_notes_survive_reload_and_resave():
    with TestClient(app) as client:
        rid = create(client, 'CIP')
        note = 'Approved internal development funding'
        payload = {'line_count': '1', 'line_key_0': 'BUILD_DESKTOP_MOD', 'phase_0': 'Build', 'adjust_0': '152', 'notes_0': 'Controlled development effort', 'investment_0': '52', 'investment_notes_0': note}
        saved = client.post(f'/estimate/{rid}/calculations', data=payload, follow_redirects=False)
        assert saved.status_code == 303
        page = client.get(f'/estimate/{rid}/calculations')
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', page.text, re.S)
        row = next(row for row in rows if 'value="BUILD_DESKTOP_MOD"' in row)
        rendered_note = unescape(re.search(r'name="investment_notes_\d+" value="([^"]*)"', row)[1])
        assert rendered_note == note
        payload['investment_notes_0'] = rendered_note
        assert client.post(f'/estimate/{rid}/calculations', data=payload, follow_redirects=False).status_code == 303

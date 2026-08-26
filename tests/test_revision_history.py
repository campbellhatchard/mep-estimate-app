import os
from pathlib import Path

os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/mep_estimate_pytest.db')
os.environ.setdefault('SESSION_SECRET', 'pytest-secret')
os.environ.setdefault('ADMIN_PASSWORD', 'TestPass123!')

from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.models import (
    AuditEvent,
    CalculationAdjustment,
    DetailAdjustment,
    EstimateCustomApplication,
    EstimateRevision,
)
from app.cip_models import CIPNonBillableAllocation, CIPScopeItem
from app.services.calculation import recalculate_and_store as mep_recalculate_and_store
from app.services.cip_calculation import recalculate_and_store as cip_recalculate_and_store


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


def test_mep_revision_history_preserves_approved_versions_and_adjustments():
    with TestClient(app) as client:
        login(client)
        rid1 = create_mep(client)
        with SessionLocal() as db:
            rev1 = db.get(EstimateRevision, rid1)
            custom = db.query(EstimateCustomApplication).filter(EstimateCustomApplication.revision_id == rid1).order_by(EstimateCustomApplication.sort_order).first()
            custom.description = 'Historical Custom Application'
            custom.complexity = 'Simple'
            db.add(DetailAdjustment(
                revision_id=rid1,
                line_key=f'CUSTOM:{custom.id}',
                description='Historical Custom Application',
                mod_hours=3,
                notes='Approved custom adjustment',
            ))
            db.add(CalculationAdjustment(
                revision_id=rid1,
                line_key='PLAN_KICKOFF',
                adjust_hours=4,
                notes='Approved kickoff adjustment',
            ))
            mep_recalculate_and_store(db, rev1)
            db.commit()
            source_hours = rev1.calculated_hours
            source_custom_sort = custom.sort_order

        approve(client, rid1)
        response = client.post(
            f'/estimate/{rid1}/new-revision',
            data={'revision_reason': 'Revise approved MEP scope while preserving historical adjustments.'},
            follow_redirects=False,
        )
        assert response.status_code == 303
        rid2 = int(response.headers['location'].rsplit('/', 1)[-1])

        with SessionLocal() as db:
            rev1 = db.get(EstimateRevision, rid1)
            rev2 = db.get(EstimateRevision, rid2)
            assert rev1.status == 'APPROVED'
            assert rev2.status == 'DRAFT'
            assert rev2.revision_no == 2
            assert rev2.calculated_hours == source_hours
            copied_custom = db.query(EstimateCustomApplication).filter(
                EstimateCustomApplication.revision_id == rid2,
                EstimateCustomApplication.sort_order == source_custom_sort,
            ).one()
            copied_detail = db.query(DetailAdjustment).filter(DetailAdjustment.revision_id == rid2).one()
            assert copied_custom.description == 'Historical Custom Application'
            assert copied_detail.line_key == f'CUSTOM:{copied_custom.id}'
            assert copied_detail.mod_hours == 3
            copied_calc = db.query(CalculationAdjustment).filter(
                CalculationAdjustment.revision_id == rid2,
                CalculationAdjustment.line_key == 'PLAN_KICKOFF',
            ).one()
            assert copied_calc.adjust_hours == 4

        history = client.get(f'/estimate/{rid2}/revisions')
        assert history.status_code == 200
        assert 'Revision History' in history.text
        assert 'Rev 1' in history.text and 'Rev 2' in history.text
        assert 'Current Approved Revision' in history.text

        # Rev 1 remains the current approved record while Rev 2 is still being edited.
        response = client.post(f'/estimate/{rid1}/new-revision', follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == f'/estimate/{rid2}'

        approve(client, rid2)
        with SessionLocal() as db:
            assert db.get(EstimateRevision, rid1).status == 'SUPERSEDED'
            assert db.get(EstimateRevision, rid2).status == 'APPROVED'
            assert db.query(AuditEvent).filter(
                AuditEvent.revision_id == rid1,
                AuditEvent.event_type == 'ESTIMATE_SUPERSEDED',
            ).count() == 1

        old_page = client.get(f'/estimate/{rid1}')
        assert old_page.status_code == 200
        assert 'Save Estimate' not in old_page.text
        assert 'SUPERSEDED' in old_page.text

        # A historical superseded revision can be used as the source of a new Draft without reopening it.
        response = client.post(
            f'/estimate/{rid1}/new-revision',
            data={'revision_reason': 'Create a third controlled revision from historical approved scope.'},
            follow_redirects=False,
        )
        assert response.status_code == 303
        rid3 = int(response.headers['location'].rsplit('/', 1)[-1])
        with SessionLocal() as db:
            rev3 = db.get(EstimateRevision, rid3)
            assert rev3.revision_no == 3 and rev3.status == 'DRAFT'
            assert rev3.calculated_hours == source_hours
            assert db.get(EstimateRevision, rid1).status == 'SUPERSEDED'


def test_cip_revision_copy_preserves_scope_phase_and_nonbillable_adjustments():
    with TestClient(app) as client:
        login(client)
        rid1 = create_cip(client)
        with SessionLocal() as db:
            rev1 = db.get(EstimateRevision, rid1)
            scope = db.query(CIPScopeItem).filter(
                CIPScopeItem.revision_id == rid1,
                CIPScopeItem.category == 'DESKTOP',
            ).order_by(CIPScopeItem.sort_order).first()
            scope.config_type = 'Baseline'
            scope.testing_adjustment = 2
            scope.testing_notes = 'Approved solution testing adjustment'
            db.add(CalculationAdjustment(
                revision_id=rid1,
                line_key='PLAN_KICKOFF',
                adjust_hours=3,
                notes='Approved CIP phase adjustment',
            ))
            db.add(CIPNonBillableAllocation(
                revision_id=rid1,
                line_key='PLAN_KICKOFF',
                hours=2,
                notes='Customer investment absorbed internally',
            ))
            cip_recalculate_and_store(db, rev1)
            db.commit()
            source_hours = rev1.calculated_hours
            source_catalog_key = scope.catalog_key

        approve(client, rid1)
        response = client.post(
            f'/estimate/{rid1}/new-revision',
            data={'revision_reason': 'Revise approved CIP scope while preserving approved adjustments.'},
            follow_redirects=False,
        )
        assert response.status_code == 303
        rid2 = int(response.headers['location'].rsplit('/', 1)[-1])

        with SessionLocal() as db:
            rev1 = db.get(EstimateRevision, rid1)
            rev2 = db.get(EstimateRevision, rid2)
            assert rev1.status == 'APPROVED' and rev2.status == 'DRAFT'
            assert rev2.calculated_hours == source_hours
            copied_scope = db.query(CIPScopeItem).filter(
                CIPScopeItem.revision_id == rid2,
                CIPScopeItem.category == 'DESKTOP',
                CIPScopeItem.catalog_key == source_catalog_key,
            ).one()
            assert copied_scope.config_type == 'Baseline'
            assert copied_scope.testing_adjustment == 2
            assert copied_scope.testing_notes == 'Approved solution testing adjustment'
            copied_calc = db.query(CalculationAdjustment).filter(
                CalculationAdjustment.revision_id == rid2,
                CalculationAdjustment.line_key == 'PLAN_KICKOFF',
            ).one()
            copied_nonbill = db.query(CIPNonBillableAllocation).filter(
                CIPNonBillableAllocation.revision_id == rid2,
                CIPNonBillableAllocation.line_key == 'PLAN_KICKOFF',
            ).one()
            assert copied_calc.adjust_hours == 3
            assert copied_nonbill.hours == 2

        history = client.get(f'/estimate/{rid2}/revisions')
        assert history.status_code == 200 and 'CIP' in history.text
        approve(client, rid2)
        with SessionLocal() as db:
            assert db.get(EstimateRevision, rid1).status == 'SUPERSEDED'
            assert db.get(EstimateRevision, rid2).status == 'APPROVED'

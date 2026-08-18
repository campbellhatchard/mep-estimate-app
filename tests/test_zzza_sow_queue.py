from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.models import EstimateRevision, User
from app.services.calculation import recalculate_and_store
from app.sow_service import go_live_support_hours


def _login(client, username='Admin', password='TestPass123!'):
    r = client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    assert r.status_code == 303, (r.status_code, r.text)


def test_sow_prepare_assign_and_approvals_queue():
    with TestClient(app) as client:
        _login(client)
        r = client.post('/admin/users/create', data={
            'username': 'SOWQueueReviewer',
            'email': 'sow-queue-reviewer@example.com',
            'password': 'ReviewPass123!',
            'active': '1',
            'roles': 'SOW_APPROVER',
        }, follow_redirects=False)
        assert r.status_code == 303, (r.status_code, r.text)
        with SessionLocal() as db:
            approver = db.query(User).filter(User.username == 'SOWQueueReviewer').one()
            assert approver.has_role('SOW_APPROVER')
            approver_id = approver.id

        r = client.post('/estimates/new', data={'product_type': 'MEP'}, follow_redirects=False)
        assert r.status_code == 303, (r.status_code, r.text)
        rid = int(r.headers['location'].rsplit('/', 1)[-1])
        with SessionLocal() as db:
            rev = db.get(EstimateRevision, rid)
            rev.customer = 'Queue Test Customer'
            rev.customer_type = 'Net_New'
            rev.entity = 'Data Systems International, Inc. dba Cloud Inventory® ("Cloud Inventory")'
            rev.erp = 'Oracle JD Edwards E1'
            rev.go_live_type = 'Remote All'
            rev.go_live_sites = 1
            recalculate_and_store(db, rev)
            db.commit()
        assert client.post(f'/estimate/{rid}/status/submit', follow_redirects=False).status_code == 303
        assert client.post(f'/estimate/{rid}/status/approve', follow_redirects=False).status_code == 303

        r = client.post(f'/estimate/{rid}/sow/create', follow_redirects=False)
        assert r.status_code == 303, (r.status_code, r.text)
        sid = int(r.headers['location'].rsplit('/', 1)[-1])
        with SessionLocal() as db:
            hours = go_live_support_hours(db, db.get(EstimateRevision, rid))

        form = {
            'agreement_type': 'Software as a Service Agreement',
            'invoice_frequency': 'Weekly',
            'project_objective': 'Deploy and configure Mobile Enterprise Platform.',
            'erp_version': 'EnterpriseOne 9.2',
            'erp_base_code_version': '9.2.6',
            'erp_tools_release': '9.2.8',
            'erp_os_version': 'Windows Server 2022',
            'erp_database_version': 'Oracle 19c',
            'mep_product_version': 'MEP 9.5.5',
            'erp_deployment_model': 'Customer Managed / Private Cloud',
            'barcode_printer_count': '0',
            'hypercare_description': 'Primary site',
            'hypercare_country': 'USA',
            'hypercare_support_type': 'Remote',
            'hypercare_hours': str(hours),
        }
        r = client.post(f'/sow/{sid}/save', data=form, follow_redirects=False)
        assert r.status_code == 303, (r.status_code, r.text)
        r = client.post(f'/sow/{sid}/finalize', follow_redirects=False)
        assert r.status_code == 303, (r.status_code, r.text)
        r = client.post(f'/sow/{sid}/send-approval', data={'approver_id': str(approver_id)}, follow_redirects=False)
        assert r.status_code == 303, (r.status_code, r.text)

        client.post('/logout', follow_redirects=False)
        _login(client, 'SOWQueueReviewer', 'ReviewPass123!')
        r = client.get('/approvals')
        assert r.status_code == 200, (r.status_code, r.text)
        assert 'Queue Test Customer' in r.text
        assert f'/sow/{sid}' in r.text

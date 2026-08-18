from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.models import EstimateRevision, User
from app.services.calculation import recalculate_and_store
from app.sow_models import SOW
from app.sow_service import go_live_support_hours


def _login(client, username='Admin', password='TestPass123!'):
    r = client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    assert r.status_code == 303, (r.status_code, r.text)


def _make_approver(client):
    r = client.post('/admin/users/create', data={
        'username': 'SOWApprovalReviewer',
        'email': 'sow-approval-reviewer@example.com',
        'password': 'ReviewPass123!',
        'active': '1',
        'roles': 'SOW_APPROVER',
    }, follow_redirects=False)
    assert r.status_code == 303, (r.status_code, r.text)
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == 'SOWApprovalReviewer').one()
        assert user.has_role('SOW_APPROVER')
        return user.id


def _make_approved_estimate(client):
    r = client.post('/estimates/new', data={'product_type': 'MEP'}, follow_redirects=False)
    assert r.status_code == 303
    rid = int(r.headers['location'].rsplit('/', 1)[-1])
    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        rev.customer = 'Approval Test Customer'
        rev.customer_type = 'Net_New'
        rev.entity = 'Data Systems International, Inc. dba Cloud Inventory® ("Cloud Inventory")'
        rev.erp = 'Oracle JD Edwards E1'
        rev.go_live_type = 'Remote All'
        rev.go_live_sites = 1
        rev.billing_rate = 250
        recalculate_and_store(db, rev)
        db.commit()
    assert client.post(f'/estimate/{rid}/status/submit', follow_redirects=False).status_code == 303
    assert client.post(f'/estimate/{rid}/status/approve', follow_redirects=False).status_code == 303
    return rid


def _form(hours):
    return {
        'agreement_type': 'Software as a Service Agreement',
        'invoice_frequency': 'Monthly',
        'project_objective': 'Deploy and configure Mobile Enterprise Platform for approved customer operations.',
        'rest_api_required': 'on',
        'barcode_printer_count': '0',
        'erp_version': 'EnterpriseOne 9.2',
        'erp_base_code_version': '9.2.6',
        'erp_tools_release': '9.2.8',
        'erp_os_version': 'Windows Server 2022',
        'erp_database_version': 'Oracle 19c',
        'mep_product_version': 'MEP 9.5.5',
        'erp_deployment_model': 'Customer Managed / Private Cloud',
        'hypercare_description': 'Primary site',
        'hypercare_country': 'USA',
        'hypercare_support_type': 'Remote',
        'hypercare_hours': str(hours),
        'device_type': 'Handheld Unit',
        'device_make_model': 'Zebra MC9400',
        'device_os_version': 'Android 13',
    }


def _prepare_and_send(client, rid, approver_id):
    r = client.post(f'/estimate/{rid}/sow/create', follow_redirects=False)
    assert r.status_code == 303, (r.status_code, r.text)
    sid = int(r.headers['location'].rsplit('/', 1)[-1])
    with SessionLocal() as db:
        hours = go_live_support_hours(db, db.get(EstimateRevision, rid))
    assert client.post(f'/sow/{sid}/save', data=_form(hours), follow_redirects=False).status_code == 303
    assert client.post(f'/sow/{sid}/finalize', follow_redirects=False).status_code == 303
    assert client.post(f'/sow/{sid}/send-approval', data={'approver_id': str(approver_id)}, follow_redirects=False).status_code == 303
    return sid, hours


def test_sow_rejection_is_immutable_and_requires_a_new_revision():
    with TestClient(app) as client:
        _login(client)
        approver_id = _make_approver(client)
        rid = _make_approved_estimate(client)
        sid, hours = _prepare_and_send(client, rid, approver_id)

        client.post('/logout', follow_redirects=False)
        _login(client, 'SOWApprovalReviewer', 'ReviewPass123!')
        assert client.post(f'/sow/{sid}/reject', data={'reason': ''}).status_code == 400
        r = client.post(
            f'/sow/{sid}/reject',
            data={'reason': 'Appendix A ERP deployment detail needs clarification.'},
            follow_redirects=False,
        )
        assert r.status_code == 303
        with SessionLocal() as db:
            rejected = db.get(SOW, sid)
            assert rejected.status == 'REJECTED'
            assert rejected.rejection_reason == 'Appendix A ERP deployment detail needs clarification.'

        # A rejected SOW itself remains locked.
        assert client.post(f'/sow/{sid}/save', data=_form(hours), follow_redirects=False).status_code in (403, 409)

        client.post('/logout', follow_redirects=False)
        _login(client)
        r = client.post(f'/sow/{sid}/new-revision', follow_redirects=False)
        assert r.status_code == 303
        sid2 = int(r.headers['location'].rsplit('/', 1)[-1])
        with SessionLocal() as db:
            new = db.get(SOW, sid2)
            assert new.status == 'DRAFT'
            assert new.sow_revision_no == 2
            assert new.template_version_id == db.get(SOW, sid).template_version_id
            assert new.erp_version == 'EnterpriseOne 9.2'


def test_sow_approval_locks_content_hash_and_regenerates_word():
    with TestClient(app) as client:
        _login(client)
        approver_id = _make_approver(client)
        rid = _make_approved_estimate(client)
        sid, _ = _prepare_and_send(client, rid, approver_id)

        client.post('/logout', follow_redirects=False)
        _login(client, 'SOWApprovalReviewer', 'ReviewPass123!')
        r = client.post(f'/sow/{sid}/approve', follow_redirects=False)
        assert r.status_code == 303, (r.status_code, r.text)
        with SessionLocal() as db:
            sow = db.get(SOW, sid)
            assert sow.status == 'APPROVED'
            assert sow.approved_by is not None
            assert len(sow.content_hash or '') == 64
            assert sow.approved_text_snapshot

        # Approval makes the SOW immutable.
        assert client.post(f'/sow/{sid}/save', data={'project_objective': 'Changed after approval'}).status_code in (403, 409)

        docx = client.get(f'/sow/{sid}/docx')
        assert docx.status_code == 200, (docx.status_code, docx.text if docx.status_code != 200 else '')
        doc = Document(BytesIO(docx.content))
        text = '\n'.join(p.text for p in doc.paragraphs)
        assert 'Approval Test Customer' in text
        assert 'Nextworld EAP Platform Administrator' not in text
        assert 'monthly basis' in text.lower()

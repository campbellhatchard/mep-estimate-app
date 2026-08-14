import os
from pathlib import Path

TEST_DB = Path('/tmp/mep_estimate_pytest.db')
if TEST_DB.exists(): TEST_DB.unlink()
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB}'
os.environ['SESSION_SECRET'] = 'pytest-secret'
os.environ['ADMIN_PASSWORD'] = 'TestPass123!'

from fastapi.testclient import TestClient
from app.run import app
from app.database import SessionLocal
from app.models import EstimateRevision, EstimateApplication, ConfigItem, ConfigurationVersion, AuditEvent, User


def login(c):
    r=c.post('/login', data={'username':'aDmIn','password':'TestPass123!'}, follow_redirects=False)
    assert r.status_code == 303


def create(c):
    r=c.post('/estimates/new', follow_redirects=False)
    assert r.status_code == 303
    return int(r.headers['location'].rsplit('/',1)[-1])


def estimate_form(rev, db):
    data={
      'customer':'Acme Test','customer_type':rev.customer_type,'opportunity_number':'OPP-001','currency':rev.currency,'entity':rev.entity,
      'upgrade_type':rev.upgrade_type,'project_type':'MEP On Prem','erp':rev.erp,'epp_install':'No','epp_integration':'None','user_count':'51 to 100',
      'go_live_type':'Remote All','security_method':'None','delivery_method':'Standard Project','upgrade_app_count':'0','label_sites':'0','label_count':'0',
      'iot_count':'0','erp_integration_count':'0','data_rep_count':'0','test_cycles':'1','go_live_sites':'1','uat_sites':'1','billing_rate':'250','base_test_pct':'0.5',
      'proposal_date':'2026-08-14','high_availability':'Yes','gateway':'No','android_change':'No','labels_required':'No','iot_required':'No',
      'erp_integration_required':'No','data_rep_required':'No','consultant_access_setup':'No','onboarding':'No','pacejet':'No','write_test_scripts':'No',
      'end_user_documentation':'No','end_user_training':'No','app_dev_training':'No'
    }
    if rev.applications:
        data[f'app_{rev.applications[0].id}']='Mod Required'
    return data


def test_end_to_end_and_case_insensitive_username():
    with TestClient(app) as c:
        assert c.get('/health').status_code == 200
        login(c)
        rid=create(c)
        with SessionLocal() as db:
            rev=db.get(EstimateRevision,rid)
            data=estimate_form(rev,db)
        r=c.post(f'/estimate/{rid}',data=data,follow_redirects=False)
        assert r.status_code==303
        with SessionLocal() as db:
            rev=db.get(EstimateRevision,rid)
            assert rev.customer=='Acme Test'
            assert rev.calculated_hours > 2
            assert rev.schedule_needs_refresh is True
            assert db.query(AuditEvent).filter(AuditEvent.revision_id==rid).count() > 2
        for path in [f'/estimate/{rid}',f'/estimate/{rid}/detail',f'/estimate/{rid}/calculations',f'/estimate/{rid}/schedule',f'/estimate/{rid}/audit','/data','/admin/users']:
            assert c.get(path).status_code==200
        assert c.get(f'/estimate/{rid}/pdf').content.startswith(b'%PDF')
        assert 'Issue Type' in c.get(f'/estimate/{rid}/jira.csv').text


def test_adjustments_require_notes_and_are_audited():
    with TestClient(app) as c:
        login(c); rid=create(c)
        r=c.post(f'/estimate/{rid}/calculations',data={'line_count':'1','line_key_0':'PLAN_KICKOFF','adjust_0':'4','notes_0':''})
        assert r.status_code==400
        r=c.post(f'/estimate/{rid}/calculations',data={'line_count':'1','line_key_0':'PLAN_KICKOFF','adjust_0':'4','notes_0':'Additional kickoff effort'},follow_redirects=False)
        assert r.status_code==303
        with SessionLocal() as db:
            assert db.query(AuditEvent).filter(AuditEvent.revision_id==rid,AuditEvent.event_type=='CALCULATION_ADJUSTED').count()==1


def test_configuration_pin_and_explicit_rebase():
    with TestClient(app) as c:
        login(c); rid=create(c)
        with SessionLocal() as db:
            rev1=db.get(EstimateRevision,rid); old_config=rev1.config_version_id; old_hours=rev1.calculated_hours
        r=c.post('/data/version/new',follow_redirects=False); assert r.status_code==303
        draft_id=int(r.headers['location'].split('version=')[1])
        with SessionLocal() as db:
            item=db.query(ConfigItem).filter(ConfigItem.config_version_id==draft_id,ConfigItem.key=='UNIT_TEST_FACTOR').one(); item_id=item.id
        r=c.post(f'/data/item/{item_id}',data={'label':'Unit Testing Factor','value_number':'0.25','value_text':'','description':'','active':'on','reason':'Regression test'},follow_redirects=False); assert r.status_code==303
        r=c.post(f'/data/version/{draft_id}/activate',follow_redirects=False); assert r.status_code==303
        with SessionLocal() as db:
            rev1=db.get(EstimateRevision,rid)
            assert rev1.config_version_id==old_config
            assert rev1.calculated_hours==old_hours
        r=c.post(f'/estimate/{rid}/new-revision?rebase=true',follow_redirects=False); assert r.status_code==303
        rid2=int(r.headers['location'].rsplit('/',1)[-1])
        with SessionLocal() as db:
            rev2=db.get(EstimateRevision,rid2)
            assert rev2.config_version_id==draft_id
            assert rev2.revision_no==2


def test_approved_revision_is_locked():
    with TestClient(app) as c:
        login(c); rid=create(c)
        assert c.post(f'/estimate/{rid}/status/submit',follow_redirects=False).status_code==303
        assert c.post(f'/estimate/{rid}/status/approve',follow_redirects=False).status_code==303
        with SessionLocal() as db: rev=db.get(EstimateRevision,rid); assert rev.status=='APPROVED'
        r=c.post(f'/estimate/{rid}',data={'customer':'Should Not Change'})
        assert r.status_code==409


def test_approved_workbook_default_baseline_and_jira_header_shape():
    with TestClient(app) as c:
        login(c); rid=create(c)
        with SessionLocal() as db:
            rev=db.get(EstimateRevision,rid)
            assert rev.calculated_hours == 2
            assert rev.calculated_fees == 500
        jira=c.get(f'/estimate/{rid}/jira.csv')
        assert jira.status_code==200
        rows=list(__import__('csv').reader(jira.text.splitlines()))
        assert len(rows[0])==27
        assert rows[0][0:7]==['Issue Type','Issue Type ID','Summary','Description','Reporter','Original estimate (in hours)','Remaining Estimate']


def test_estimate_business_validation_blocks_inconsistent_go_live():
    with TestClient(app) as c:
        login(c); rid=create(c)
        with SessionLocal() as db:
            rev=db.get(EstimateRevision,rid)
            data=estimate_form(rev,db)
        data['go_live_type']='None'
        r=c.post(f'/estimate/{rid}',data=data)
        assert r.status_code==400
        assert 'Go Live' in r.text or 'go-live' in r.text.lower()


def test_deployed_over_change_resets_baseline_applications():
    with TestClient(app) as c:
        login(c); rid=create(c)
        with SessionLocal() as db:
            rev=db.get(EstimateRevision,rid)
            data=estimate_form(rev,db)
        assert c.post(f'/estimate/{rid}',data=data,follow_redirects=False).status_code==303
        with SessionLocal() as db:
            rev=db.get(EstimateRevision,rid)
            assert any(a.config_type != 'No Config' for a in rev.applications)
            data=estimate_form(rev,db)
            data['erp']='Oracle Fusion'
            # The Estimate page resets every visible application/package selector before
            # posting an ERP/Deployed Over change. Model that exact user interaction.
            for key in list(data):
                if key.startswith('app_'):
                    data[key]='No Config'
        assert c.post(f'/estimate/{rid}',data=data,follow_redirects=False).status_code==303
        with SessionLocal() as db:
            rev=db.get(EstimateRevision,rid)
            assert rev.erp=='Oracle Fusion'
            assert rev.applications
            assert all(a.config_type=='No Config' for a in rev.applications)


def test_multi_role_user_email_and_active_management():
    with TestClient(app) as c:
        login(c)
        r=c.post('/admin/users/create',data={
            'username':'MultiRoleUser','email':'user@example.com','password':'UserPass123!',
            'active':'on','roles':['ESTIMATOR','REVIEWER']
        },follow_redirects=False)
        assert r.status_code==303
        with SessionLocal() as db:
            user=db.query(User).filter(User.username_normalized=='multiroleuser').one()
            uid=user.id
            assert user.email=='user@example.com'
            assert set(user.role_names)=={'ESTIMATOR','REVIEWER'}
            assert user.active is True
        r=c.post(f'/admin/users/{uid}/update',data={
            'email':'updated@example.com','roles':['APPROVER','READ_ONLY']
        },follow_redirects=False)
        assert r.status_code==303
        with SessionLocal() as db:
            user=db.get(User,uid)
            assert user.email=='updated@example.com'
            assert set(user.role_names)=={'APPROVER','READ_ONLY'}
            assert user.active is False
            assert db.query(AuditEvent).filter(AuditEvent.event_type=='USER_UPDATED').count()>=1


def test_user_facing_terminology_is_normalized_without_changing_internal_values():
    with TestClient(app) as c:
        login(c); rid=create(c)
        page=c.get(f'/estimate/{rid}')
        assert page.status_code==200
        assert 'SAP ECC 6.0' in page.text
        assert 'SAP S/4HANA 2022' in page.text
        assert 'Oracle NetSuite' in page.text
        assert 'Install Base' in page.text
        assert 'Baseline Applications:' in page.text

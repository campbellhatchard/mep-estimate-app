"""DEF-RO-001/002: rendered controls must match server authorization.

These are application integration tests, not a replacement for live browser UAT.
A lifecycle-only readonly flag or a role-only locked-state check must fail here.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from lxml import html

from app import main as core
from app.auth import hash_password
from app.cip_models import CIPRevisionInput
from app.database import SessionLocal
from app.models import AuditEvent, EstimateRevision, ScheduleTask, User, UserRole
from app.run import app
from app.sow_models import SOW

# Literal expectations preserve current authoring grants and any-role semantics.
PROFILES = [
    (('READ_ONLY',), False), (('TOOLS_ADMIN',), False), (('SOW_APPROVER',), False),
    (('ADMIN',), True), (('ESTIMATOR',), True), (('REVIEWER',), True),
    (('APPROVER',), True), (('READ_ONLY', 'ESTIMATOR'), True),
]
STATES = [('DRAFT', True), ('REVIEW', True), ('APPROVED', False),
          ('FINAL', False), ('SUPERSEDED', False)]


def login(client, username='Admin', password='TestPass123!'):
    response = client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    assert response.status_code == 303


def new_estimate(client, product):
    response = client.post('/estimates/new', data={'product_type': product}, follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers['location'].rsplit('/', 1)[-1])


def document(response):
    assert response.status_code == 200, response.text[:500]
    return html.fromstring(response.text)


def editable_controls(tree):
    return tree.xpath('//main//*[self::input or self::textarea or self::select]'
                      '[not(@type="hidden") and not(@disabled) and not(@readonly)]')


def mutation_buttons(tree):
    return [b.text_content().strip() for b in tree.xpath('//main//button')
            if b.text_content().strip() != 'Explain']


@pytest.fixture(scope='module')
def environment():
    with TestClient(app) as client:
        login(client)
        users = {}
        password = 'ReadOnlyRegression123!'
        encoded = hash_password(password)
        with SessionLocal() as db:
            for roles, _ in PROFILES:
                name = 'ROFix-' + uuid4().hex[:10]
                u = User(username=name, username_normalized=name.casefold(), password_hash=encoded,
                         role=roles[0], active=True, roles=[UserRole(role=r) for r in roles])
                db.add(u)
                users[roles] = name
            db.commit()
        estimates = {}
        for product in ('MEP', 'CIP'):
            rid = new_estimate(client, product)
            assert client.get(f'/estimate/{rid}/schedule').status_code == 200
            estimates[product] = rid
        sows = {}
        for product in ('MEP', 'CIP'):
            for small in (False, True):
                rid = new_estimate(client, product)
                with SessionLocal() as db:
                    rev = db.get(EstimateRevision, rid)
                    rev.status = 'APPROVED'
                    rev.customer = 'Read Only regression'
                    rev.customer_type = 'Install_Base' if small else 'Net_New'
                    rev.project_type = 'Small Project' if small else ('MEP Cloud' if product == 'MEP' else 'CIP Install')
                    if product == 'CIP':
                        db.get(CIPRevisionInput, rid).project_type = rev.project_type
                    db.commit()
                response = client.post(f'/estimate/{rid}/sow/create', follow_redirects=False)
                assert response.status_code == 303, response.text
                sows[(product, small)] = int(response.headers['location'].rsplit('/', 1)[-1])
        yield client, users, password, estimates, sows


@pytest.mark.parametrize('roles,author', PROFILES)
@pytest.mark.parametrize('state,working', STATES)
@pytest.mark.parametrize('product', ['MEP', 'CIP'])
def test_estimate_pages_respect_role_and_state(environment, roles, author, state, working, product):
    client, users, password, estimates, _ = environment
    rid = estimates[product]
    with SessionLocal() as db:
        db.get(EstimateRevision, rid).status = state
        db.commit()
    login(client, users[roles], password)
    for path in ('', '/detail', '/calculations', '/schedule'):
        tree = document(client.get(f'/estimate/{rid}{path}'))
        if author and working and (path != "/schedule" or state == "DRAFT"):
            assert editable_controls(tree), (roles, state, path)
            assert any(text.startswith('Save') for text in mutation_buttons(tree))
        else:
            assert not editable_controls(tree), (roles, state, path)
            assert not any(text.startswith('Save') for text in mutation_buttons(tree))
        if not author:
            assert not mutation_buttons(tree), (roles, state, path, mutation_buttons(tree))
        if path == '':
            buttons = mutation_buttons(tree)
            assert ('Submit for Review' in buttons) == (author and state == 'DRAFT')
            assert ('New Revision' in buttons) == (author and state in ('APPROVED', 'FINAL'))
    history = document(client.get(f'/estimate/{rid}/revisions'))
    assert bool(history.xpath('//button[contains(., "Create New Revision From This")]')) == (author and not working)


@pytest.mark.parametrize('roles,author', PROFILES)
def test_repository_creation_link_matches_role(environment, roles, author):
    client, users, password, _, _ = environment
    login(client, users[roles], password)
    tree = document(client.get('/estimates'))
    assert bool(tree.xpath('//a[@href="/estimates/new"]')) == author
    assert tree.xpath('//input[@id="estimateSearch" and not(@disabled)]')


@pytest.mark.parametrize('roles,author', PROFILES)
@pytest.mark.parametrize('family', [('MEP', False), ('CIP', False), ('MEP', True), ('CIP', True)])
def test_all_draft_sow_families_respect_authoring_roles(environment, roles, author, family):
    client, users, password, _, sows = environment
    sid = sows[family]
    with SessionLocal() as db:
        db.get(SOW, sid).status = 'DRAFT'
        db.commit()
    login(client, users[roles], password)
    tree = document(client.get(f'/sow/{sid}'))
    assert bool(editable_controls(tree)) == author
    assert bool(tree.xpath('//button[normalize-space(.)="Add Location"]')) == author
    assert bool(tree.xpath('//button[normalize-space(.)="Save SOW Details"]')) == author
    assert tree.xpath(f'//a[@href="/sow/{sid}/pdf"]')
    assert tree.xpath(f'//a[@href="/sow/{sid}/docx"]')


@pytest.mark.parametrize('state', ['FINALIZED', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED'])
@pytest.mark.parametrize('family', [('MEP', False), ('CIP', False), ('MEP', True), ('CIP', True)])
def test_locked_sow_authoring_fields_stay_disabled_for_authors(environment, state, family):
    client, users, password, _, sows = environment
    sid = sows[family]
    with SessionLocal() as db:
        sow = db.get(SOW, sid)
        sow.status = state
        db.commit()
    login(client, users[('ESTIMATOR',)], password)
    tree = document(client.get(f'/sow/{sid}'))
    # Workflow fields can remain available; only the authoring form is immutable.
    form = tree.xpath('//form[contains(@action, "/save")]')[0]
    assert not form.xpath('.//*[self::input or self::textarea or self::select][not(@type="hidden") and not(@disabled) and not(@readonly)]')
    assert not form.xpath('.//button')


@pytest.mark.parametrize('product', ['MEP', 'CIP'])
@pytest.mark.parametrize('roles', [('READ_ONLY',), ('TOOLS_ADMIN',), ('SOW_APPROVER',)])
def test_reading_empty_schedule_or_jira_does_not_generate_persisted_tasks(environment, product, roles):
    client, users, password, _, _ = environment
    login(client)
    rid = new_estimate(client, product)
    login(client, users[roles], password)
    page = document(client.get(f'/estimate/{rid}/schedule'))
    assert 'has not been generated' in page.text_content()
    export = client.get(f'/estimate/{rid}/jira.csv')
    assert export.status_code == 409
    with SessionLocal() as db:
        assert db.query(ScheduleTask).filter_by(revision_id=rid).count() == 0


@pytest.mark.parametrize('product', ['MEP', 'CIP'])
def test_readonly_forged_estimate_writes_leave_record_schedule_and_audit_unchanged(environment, product):
    client, users, password, estimates, _ = environment
    rid = estimates[product]
    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        rev.status = 'DRAFT'
        rev.opportunity_number = 'AUTHORIZED BASELINE'
        db.commit()
        baseline = (rev.opportunity_number, rev.status, rev.calculated_hours, rev.calculated_fees,
                    len(rev.estimate.revisions), db.query(AuditEvent).filter_by(revision_id=rid).count(),
                    [(t.id, t.comments, t.resource_assigned) for t in db.query(ScheduleTask).filter_by(revision_id=rid).order_by(ScheduleTask.id)])
    login(client, users[('READ_ONLY',)], password)
    attempts = [('', {'opportunity_number':'UNAUTHORIZED'}), ('/detail', {'line_count':'1','mod_0':'1','added_0':'1'}),
                ('/calculations', {'line_count':'1','line_key_0':'PLAN_PM','adjust_0':'1'}),
                ('/schedule', {'action':'regenerate'}), ('/status/submit', {}), ('/status/approve', {}),
                ('/new-revision', {'revision_reason':'Unauthorized revision'}),
                ('/assumptions', {'text':'Unauthorized assumption'})]
    for suffix, data in attempts:
        response = client.post(f'/estimate/{rid}{suffix}', data=data, follow_redirects=False)
        assert response.status_code == 403, (suffix, response.status_code, response.text)
    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        actual = (rev.opportunity_number, rev.status, rev.calculated_hours, rev.calculated_fees,
                  len(rev.estimate.revisions), db.query(AuditEvent).filter_by(revision_id=rid).count(),
                  [(t.id, t.comments, t.resource_assigned) for t in db.query(ScheduleTask).filter_by(revision_id=rid).order_by(ScheduleTask.id)])
        assert actual == baseline


@pytest.mark.parametrize('family', [('MEP', False), ('CIP', False), ('MEP', True), ('CIP', True)])
def test_readonly_forged_sow_save_is_atomic(environment, family):
    client, users, password, _, sows = environment
    sid = sows[family]
    with SessionLocal() as db:
        sow = db.get(SOW, sid)
        sow.status = 'DRAFT'
        db.commit()
        baseline = (sow.project_objective, sow.status, len(sow.hypercare_locations), len(sow.devices), db.query(AuditEvent).count())
    login(client, users[('READ_ONLY',)], password)
    response = client.post(f'/sow/{sid}/save', data={'project_objective':'UNAUTHORIZED','hypercare_description':'UNAUTHORIZED','hypercare_hours':'1'}, follow_redirects=False)
    assert response.status_code == 403
    with SessionLocal() as db:
        sow = db.get(SOW, sid)
        assert (sow.project_objective, sow.status, len(sow.hypercare_locations), len(sow.devices), db.query(AuditEvent).count()) == baseline


@pytest.mark.parametrize('product', ['MEP', 'CIP'])
@pytest.mark.parametrize('roles', [('READ_ONLY',), ('TOOLS_ADMIN',), ('SOW_APPROVER',)])
def test_small_project_empty_sow_does_not_offer_creation_to_non_authors(environment, product, roles):
    client, users, password, _, _ = environment
    login(client)
    rid = new_estimate(client, product)
    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        rev.status = 'APPROVED'
        rev.customer_type = 'Install_Base'
        rev.project_type = 'Small Project'
        if product == 'CIP':
            db.get(CIPRevisionInput, rid).project_type = 'Small Project'
        db.commit()
    login(client, users[roles], password)
    tree = document(client.get(f'/estimate/{rid}/sow'))
    assert not tree.xpath('//button[normalize-space(.)="Create Small Project SOW"]')
    assert client.post(f'/estimate/{rid}/sow/create', follow_redirects=False).status_code == 403


@pytest.mark.parametrize('product', ['MEP', 'CIP'])
def test_mixed_readonly_author_can_save_and_readonly_can_export_existing_schedule(environment, product):
    client, users, password, estimates, _ = environment
    rid = estimates[product]
    with SessionLocal() as db:
        db.get(EstimateRevision, rid).status = 'DRAFT'
        db.commit()
    login(client, users[('READ_ONLY', 'ESTIMATOR')], password)
    form = document(client.get(f'/estimate/{rid}')).get_element_by_id('estimateForm')
    payload = dict(form.form_values())
    payload['opportunity_number'] = 'AUTHORIZED MIXED ROLE'
    result = client.post(f'/estimate/{rid}', data=payload, follow_redirects=False)
    assert result.status_code == 303, result.text
    with SessionLocal() as db:
        assert db.get(EstimateRevision, rid).opportunity_number == 'AUTHORIZED MIXED ROLE'
        task_ids = [t.id for t in db.query(ScheduleTask).filter_by(revision_id=rid).order_by(ScheduleTask.id)]
    login(client, users[('READ_ONLY',)], password)
    for suffix in ('/schedule.csv', '/jira.csv'):
        assert client.get(f'/estimate/{rid}{suffix}').status_code == 200
    with SessionLocal() as db:
        assert [t.id for t in db.query(ScheduleTask).filter_by(revision_id=rid).order_by(ScheduleTask.id)] == task_ids

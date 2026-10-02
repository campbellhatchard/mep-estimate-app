"""Browser release guard for DEF-RO-001 and DEF-RO-002 (synthetic localhost only)."""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.support.flows import (
    click_and_wait, create_estimate, login, logout, select_and_save, url,
)

pytestmark = [pytest.mark.e2e, pytest.mark.smoke, pytest.mark.release]


EDITABLE = ('main input:enabled:not([type="hidden"]):not([readonly]), '
            'main textarea:enabled:not([readonly]), main select:enabled')
MUTATIONS = re.compile(r'^(Save|Submit|Return|Approve|New Revision|Rebase|Regenerate|Add |Remove|Create New Revision)')


def switch_user(page, app_url, spec):
    logout(page)
    login(page, app_url, spec.username, spec.password)


def assert_view_only(page):
    expect(page.locator(EDITABLE)).to_have_count(0)
    expect(page.get_by_role('button', name=MUTATIONS)).to_have_count(0)


@pytest.mark.parametrize('product', ['MEP', 'CIP'])
def test_readonly_estimate_forms_and_revision_actions(page, app_url, user_specs, product):
    author, reader = user_specs['multi'], user_specs['readonly']
    login(page, app_url, author.username, author.password)
    rid = create_estimate(page, app_url, product)
    page.get_by_role('link', name='Schedule', exact=True).click()
    expect(page.get_by_role('button', name='Save Schedule Changes')).to_be_visible()
    switch_user(page, app_url, reader)
    expect(page.get_by_role('link', name='+ New Estimate', exact=True)).to_have_count(0)
    for suffix in ('', '/detail', '/calculations', '/schedule'):
        page.goto(url(app_url, f'/estimate/{rid}{suffix}'))
        assert_view_only(page)
        page.reload()
        assert_view_only(page)
    page.goto(url(app_url, f'/estimate/{rid}/calculations'))
    page.get_by_role('button', name='Explain', exact=True).first.click()
    expect(page.locator('.trace:not(.hidden)').first).to_be_visible()
    switch_user(page, app_url, author)
    page.goto(url(app_url, f'/estimate/{rid}'))
    click_and_wait(page, page.get_by_role('button', name='Submit for Review', exact=True))
    click_and_wait(page, page.get_by_role('button', name='Approve / Final', exact=True))
    expect(page.get_by_role('button', name='New Revision', exact=True)).to_be_visible()
    switch_user(page, app_url, reader)
    page.goto(url(app_url, f'/estimate/{rid}'))
    assert_view_only(page)
    page.get_by_role('link', name='Revision History', exact=True).click()
    expect(page.get_by_role('button', name='Create New Revision From This')).to_have_count(0)


@pytest.mark.parametrize('product,small', [('MEP', False), ('CIP', False), ('MEP', True), ('CIP', True)])
def test_readonly_sow_authoring_all_four_families(page, app_url, user_specs, product, small):
    author, reader = user_specs['multi'], user_specs['readonly']
    login(page, app_url, author.username, author.password)
    rid = create_estimate(page, app_url, product)
    if small:
        select_and_save(page, rid, page.get_by_label('Customer Type:'), 'Install_Base')
        select_and_save(page, rid, page.get_by_label('Project Type:'), 'Small Project')
    click_and_wait(page, page.get_by_role('button', name='Submit for Review', exact=True))
    click_and_wait(page, page.get_by_role('button', name='Approve / Final', exact=True))
    switch_user(page, app_url, reader)
    page.goto(url(app_url, f'/estimate/{rid}/sow'))
    expect(page.get_by_role('button', name=re.compile('^(Prepare SOW|Create Small Project SOW)$'))).to_have_count(0)
    switch_user(page, app_url, author)
    page.goto(url(app_url, f'/estimate/{rid}/sow'))
    click_and_wait(page, page.get_by_role('button', name='Create Small Project SOW' if small else 'Prepare SOW', exact=True))
    sid = int(page.url.rstrip('/').rsplit('/', 1)[-1])
    expect(page.get_by_role('textbox', name='Project Objective', exact=True)).to_be_editable()
    page.get_by_role('textbox', name='Project Objective', exact=True).fill('Authorized regression objective')
    click_and_wait(page, page.get_by_role('button', name='Save SOW Details', exact=True))
    switch_user(page, app_url, reader)
    page.goto(url(app_url, f'/sow/{sid}'))
    assert_view_only(page)
    expect(page.get_by_role('textbox', name='Project Objective', exact=True)).to_have_value('Authorized regression objective')
    expect(page.get_by_role('link', name='Open PDF', exact=True)).to_be_visible()
    expect(page.get_by_role('link', name='Draft Word SOW', exact=True)).to_be_visible()
    page.reload()
    assert_view_only(page)

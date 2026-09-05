from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cip_domain import _ensure_dynamic_scope
from app.cip_models import CIPNonBillableAllocation, CIPRevisionInput, CIPScopeItem
from app.database import SessionLocal
from app.models import ConfigurationVersion, EstimateApplication, EstimateCustomApplication, EstimateRevision
from app.run import app
from app.services.calculation_v101 import calculation as mep_calculation
from app.services.cip_calculation_v101 import calculation as cip_calculation

EXPECTED = json.loads((Path(__file__).parent / "golden" / "expected_v03251.json").read_text(encoding="utf-8"))

def _login(client):
    r=client.post('/login',data={'username':'Admin','password':'TestPass123!'},follow_redirects=False); assert r.status_code==303

def _create(client, product):
    r=client.post('/estimates/new',data={'product_type':product},follow_redirects=False); assert r.status_code==303; return int(r.headers['location'].rstrip('/').rsplit('/',1)[-1])

def _seed_config(db,name): return db.query(ConfigurationVersion).filter(ConfigurationVersion.name==name).one()

def _mep_setup(db, rev, scenario):
    rev.config_version_id=_seed_config(db,'MEP Estimate Model 2026.08.1').id; rev.engine_version='1.0.1'
    app=db.query(EstimateApplication).filter_by(revision_id=rev.id,kind='APPLICATION').order_by(EstimateApplication.sort_order).first()
    package=db.query(EstimateApplication).filter_by(revision_id=rev.id,kind='PACKAGE').order_by(EstimateApplication.sort_order).first()
    custom=db.query(EstimateCustomApplication).filter_by(revision_id=rev.id).order_by(EstimateCustomApplication.sort_order).first()
    if scenario=='MEP-01-default': return
    if scenario=='MEP-02-on-prem': rev.project_type='MEP On Prem'
    elif scenario=='MEP-03-small-install-base': rev.project_type='Small Project'; rev.customer_type='Install_Base'
    elif scenario=='MEP-04-epp-cloud': rev.project_type='EPP Cloud'; rev.epp_install='Cloud'; rev.label_sites=1
    elif scenario=='MEP-05-epp-on-prem': rev.project_type='EPP On Prem'; rev.epp_install='On Prem'; rev.label_sites=2; rev.gateway=True
    elif scenario=='MEP-06-platform-move-on-prem': rev.project_type='Platform Move On Prem'
    elif scenario=='MEP-07-platform-move-cloud': rev.project_type='Platform Move To Cloud'
    elif scenario=='MEP-08-one-mod-app': app.config_type='Mod Required'; rev.go_live_sites=1; rev.go_live_type='Remote All'
    elif scenario=='MEP-09-package-pkg16': package.config_type='PKG16'; rev.go_live_sites=1; rev.go_live_type='Remote All'
    elif scenario=='MEP-10-components': custom.description='Controlled Moderate Custom Application'; custom.complexity='Moderate'; rev.labels_required=True; rev.label_count=2; rev.erp_integration_required=True; rev.erp_integration_count=1; rev.data_rep_required=True; rev.data_rep_count=1; rev.go_live_sites=2; rev.go_live_type='Remote All'
    elif scenario=='MEP-11-uat-heavy': app.config_type='Mod Required'; rev.test_cycles=3; rev.uat_sites=3; rev.base_test_pct=.5; rev.go_live_sites=2; rev.go_live_type='On-Site All'
    elif scenario=='MEP-12-options-markup': app.config_type='Mod Required'; rev.delivery_method='Add 20 %'; rev.app_dev_training=True; rev.end_user_documentation=True; rev.end_user_training=True; rev.user_count='51 to 100'; rev.pacejet=True; rev.go_live_sites=1; rev.go_live_type='Remote All'
    else: raise AssertionError(scenario)
    db.flush()

def _scope(db,rid,category): return db.query(CIPScopeItem).filter(CIPScopeItem.revision_id==rid,CIPScopeItem.category==category).order_by(CIPScopeItem.sort_order,CIPScopeItem.id).all()

def _cip_setup(db, rev, scenario):
    rev.config_version_id=_seed_config(db,'CIP Estimate Model 2026.08.1').id; rev.engine_version='CIP-1.0.1'; inp=db.get(CIPRevisionInput,rev.id); inp.release_key='RELEASE_26_2'
    if scenario=='CIP-01-default': return
    if scenario=='CIP-02-install-base': rev.customer_type='Install_Base'
    elif scenario=='CIP-03-small-install-base': rev.customer_type='Install_Base'; rev.project_type='Small Project'; inp.project_type='Small Project'
    elif scenario=='CIP-04-epp-cloud': rev.project_type='EPP Cloud'; inp.project_type='EPP Cloud'; inp.epp_install='Cloud'; inp.label_sites=1
    elif scenario=='CIP-05-epp-on-prem': rev.project_type='EPP On Prem'; inp.project_type='EPP On Prem'; inp.epp_install='On Prem'; inp.label_sites=1; inp.gateway=True
    elif scenario=='CIP-06-desktop-baseline': _scope(db,rev.id,'DESKTOP')[0].config_type='Baseline'
    elif scenario=='CIP-07-desktop-mod': _scope(db,rev.id,'DESKTOP')[0].config_type='Mod Required'
    elif scenario=='CIP-08-mobile-custom': _scope(db,rev.id,'MOBILE')[0].config_type='Baseline'; c=_scope(db,rev.id,'CUSTOM_DESKTOP')[0]; c.description='Controlled Custom Desktop'; c.config_type='Moderate'
    elif scenario=='CIP-09-report-label-modifiers': report=_scope(db,rev.id,'REPORT')[0]; report.description='Controlled Complex Report'; report.config_type='Complex'; inp.labels_required=True; inp.label_count=1; inp.test_food_pharma=True; inp.test_monitored_session=True; _ensure_dynamic_scope(db,rev,inp)
    elif scenario=='CIP-10-boomi': inp.custom_boomi_required=True; inp.custom_boomi_count=1; _ensure_dynamic_scope(db,rev,inp)
    elif scenario=='CIP-11-rest-multi': inp.rest_required=True; inp.rest_interface_count=1; _ensure_dynamic_scope(db,rev,inp); _scope(db,rev.id,'REST')[0].app_count=3
    elif scenario=='CIP-12-combined':
        inp.test_ihu=inp.test_lot_serial=inp.test_food_pharma=inp.test_location_dimension=inp.test_setup_customer_data=inp.test_monitored_session=True; inp.testing_cycles=2; inp.uat_sites=2; inp.go_live_sites=2; inp.go_live_type='Remote All'; _scope(db,rev.id,'DESKTOP')[0].config_type='Mod Required'; _scope(db,rev.id,'MOBILE')[0].config_type='Mod Required'; report=_scope(db,rev.id,'REPORT')[0]; report.description='Controlled Moderate Report'; report.config_type='Moderate'; inp.custom_boomi_required=True; inp.custom_boomi_count=1; inp.rest_required=True; inp.rest_interface_count=1; _ensure_dynamic_scope(db,rev,inp); _scope(db,rev.id,'REST')[0].app_count=2; db.add(CIPNonBillableAllocation(revision_id=rev.id,line_key='PLAN_KICKOFF',hours=6,notes='Controlled internal Plan allocation'))
    else: raise AssertionError(scenario)
    db.flush()

@pytest.mark.parametrize('case',EXPECTED['mep'],ids=lambda c:c['id'])
def test_mep_golden_scenario_matrix(case):
    with TestClient(app) as client:
        _login(client); rid=_create(client,'MEP')
        with SessionLocal() as db:
            rev=db.get(EstimateRevision,rid); _mep_setup(db,rev,case['id']); _,summary,_,_=mep_calculation(db,rev); assert summary['hours']==pytest.approx(case['hours']); assert summary['fees']==pytest.approx(case['fees'])

@pytest.mark.parametrize('case',EXPECTED['cip'],ids=lambda c:c['id'])
def test_cip_golden_scenario_matrix(case):
    with TestClient(app) as client:
        _login(client); rid=_create(client,'CIP')
        with SessionLocal() as db:
            rev=db.get(EstimateRevision,rid); _cip_setup(db,rev,case['id']); _,summary,_,_=cip_calculation(db,rev); assert summary['investment_hours']==pytest.approx(case['investment_hours']); assert summary['non_billable_hours']==pytest.approx(case['non_billable_hours']); assert summary['total_internal_hours']==pytest.approx(case['total_internal_hours']); assert summary['fees']==pytest.approx(case['fees']); assert summary['solution_testing_hours']==pytest.approx(case['solution_testing_hours'])

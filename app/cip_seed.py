from __future__ import annotations
import json
from datetime import datetime
from sqlalchemy.orm import Session
from .cip_models import ConfigurationProduct, PRODUCT_CIP
from .models import ConfigItem, ConfigurationVersion
from .seed import slug

RELEASES = [('RELEASE_25_2', 'Release 25.2', 252), ('RELEASE_25_3', 'Release 25.3', 253), ('RELEASE_26_1', 'Release 26.1', 261), ('RELEASE_26_2', 'Release 26.2', 262)]
DESKTOP = ['INB Shipments', 'INB Shipments Integration', 'INB Orders', 'INB Orders Receipt', 'INB Allocations Report', 'Inspections Inquiry', 'Inspections Review', 'INV Adjustment', 'INV Transfer', 'IHU Pack Unpack', 'Replenishments to Pick', 'Ownership Transfer', 'Job Transfer', 'INV Requests', 'INV Request Execution', 'KWO Management', 'INV Overview', 'INV Balance Inquiry', 'Allocation Inquiry', 'Transaction Inquiry', 'Serial Inquiry', 'Lots Expired', 'Lots Expiring Today', 'Lots Expiring Next Week', 'Replenishments Inquiry', 'Field Inventory Transactions', 'Create CycCnt', 'CycCnt Inquiry', 'CycCnt Review and Approve', 'Outbound Orders', 'Wave Manager', 'Single Order Pick', 'Order Pack', 'Shipment Management', 'OPU Unit Nest Unnest', 'Shipment Inquiry', 'Outbound Allocations Rept']
MOBILE = ['Inbound Receipt (by order, supplier, item, inbound shipment, inbound shipment packing unit)', 'Inspection', 'Inventory Adjustment', 'Field Inventory Adjustment **MEP Offline**', 'Inventory Transfer', 'IHU Pack Unpack', 'Replenishment', 'Ownership Transfer', 'Job / Job Cost Code Transfer', 'Inventory Request / Accept', 'Kit Work Order Pick', 'Kit Work Order Complete', 'Single Order Pick', 'Order Pack', 'Load Truck', 'OPU Nest Unnest', 'Putaway', 'Inventory Inquiry', 'Field Inventory Inquiry **MEP Offline**', 'Miscellaneous Issue', 'Miscellaneous Receipt', 'IHU Nest Unnest', 'IHU Transfer', 'Cycle Count', 'Order Unpick', 'Wave Pick', 'Zone Pick', 'Ship Outbound Shipment', 'Order Unpack', 'Barcode Reader', 'Inbound Shipment Status App']
INTEGRATIONS = ['Item Replicate', 'PO Replicate', 'PO Receipt Transaction Post', 'SO Replicate', 'SO Ship Confirm Transaction Post', 'TO Replicate (single and double-sided)', 'TO Ship Confirm Transaction Post (single and double-sided)', 'TO Receipt Transaction Post (single and double-sided)', 'Inventory Adjustment Transaction Post', 'Inventory Transfer Transaction Post', 'Vendor Return Material Authorization Replicate', 'Vendor Return Material Authorization Transaction Post', 'Customer Return Material Authorization Replicate', 'Customer Return Material Authorization Transaction Post', 'Kit Work Order Item Replicate', 'Kit Work Order Replicate', 'Kit Work Order Issues Transaction Post', 'Kit Work Order Completions Transactions Post', 'Sales Kits', 'ASN to Outbound Order Ship Destination', 'Inventory Request Transaction Post', 'Materials <> Inventory (CI) balance reconciliation report', 'Inspection Fail, Inspection Fail>Pass, Pass>Fail', 'Integration Configuration Settings', 'Mobile Outbound Order Pack (PaceJet)', 'Mobile Outbound Order Ship (PaceJet)']
PARAMS = {'UNIT_TEST_FACTOR': 0.15, 'IM_FACTOR': 0.2, 'PREP_FACTOR': 0.1, 'CONTINGENCY_FACTOR': 0.15, 'SMALL_PROJECT_CONTINGENCY_FACTOR': 0.075, 'KICKOFF_CIP_HOURS': 8, 'KICKOFF_EPP_HOURS': 4, 'KICKOFF_SMALL_HOURS': 2, 'EPP_ON_PREM_INSTALL_HOURS': 8, 'EPP_PRINT_BRIDGE_ADDITIONAL_SITE_HOURS': 3, 'GATEWAY_INSTALL_HOURS': 8, 'ACCESS_SETUP_HOURS': 2, 'FACILITY_REVIEW_HOURS': 32, 'PACEJET_REQUIREMENTS_HOURS': 8, 'ORIENTATION_PREP_PER_STANDARD_APP': 1, 'ORIENTATION_SESSION_PER_COMPONENT': 0.5, 'GAP_ANALYSIS_PER_COMPONENT': 0.35, 'BRD_FACTOR': 0.15, 'DESIGN_DEV_DATA_PREP_HOURS': 4, 'DESIGN_DATA_IMPORT_HOURS': 16, 'DESIGN_VALIDATE_DEV_DATA_HOURS': 16, 'DESIGN_CLIENT_DATA_UPLOAD_HOURS': 8, 'INITIAL_TEST_SCRIPT_FACTOR': 0.01, 'APPROVE_TEST_SCRIPT_FACTOR': 0.05, 'CI_WRITE_TEST_SCRIPT_FACTOR': 0.05, 'INTERNAL_DESIGN_REVIEW_HOURS': 4, 'SOLUTION_DESIGN_FACTOR': 0.05, 'SSO_SETUP_HOURS': 16, 'MOBILE_DEV_TRAINING_HOURS': 24, 'CIP_DESKTOP_DEV_TRAINING_HOURS': 24, 'MODULE_SETTINGS_NET_NEW_HOURS': 24, 'MODULE_SETTINGS_INSTALL_BASE_HOURS': 0, 'BASELINE_DASHBOARD_HOURS': 4, 'ADMIN_TRAINING_HOURS': 2, 'PACEJET_VALIDATION_HOURS': 4, 'APP_DEMO_HOURS_PER_APP': 1.5, 'APP_REMEDIATION_FACTOR': 0.5, 'SOLUTION_WORKSHOP_FACTOR': 0.5, 'METADATA_MIGRATION_FACTOR': 0.025, 'METADATA_MIGRATION_MIN_NET_NEW_HOURS': 4, 'END_USER_TRAINING_HOURS_PER_COMPONENT': 1, 'END_USER_DOC_HOURS_PER_COMPONENT': 2, 'KEY_USER_TRAINING_HOURS_PER_COMPONENT': 0.5, 'UAT_PREP_HOURS': 2, 'LIMITED_LOAD_TEST_INSTALL_BASE_HOURS': 24, 'GO_LIVE_READINESS_INSTALL_BASE_HOURS': 1, 'GO_LIVE_READINESS_NET_NEW_HOURS': 4, 'GO_LIVE_PREP_INSTALL_BASE_HOURS': 2, 'GO_LIVE_PREP_NET_NEW_HOURS': 24, 'GO_LIVE_MEETING_INSTALL_BASE_HOURS': 4, 'GO_LIVE_MEETING_OTHER_HOURS': 2, 'STANDARD_MOD_REQUIRED_HOURS': 8, 'REPORT_TEST_BASE_FACTOR': 0.3, 'CUSTOM_MOBILE_TEST_BASE_FACTOR': 0.3, 'LABEL_DEV_HOURS': 2, 'LABEL_TEST_BASE_FACTOR': 0.2, 'BOOMI_CUSTOM_DEV_HOURS': 16, 'BOOMI_CUSTOM_TEST_BASE_FACTOR': 0.065, 'INTEGRATION_TEST_BASE_FACTOR': 0.055, 'REST_SERVICE_DEV_HOURS': 8, 'REST_FIRST_APP_HOURS': 4, 'REST_ADDITIONAL_APP_HOURS': 2, 'REST_TEST_FACTOR': 0.1, 'DESKTOP_BASELINE_SMALL_CHANGE_FACTOR': 0.5, 'MOBILE_BASELINE_SMALL_CHANGE_FACTOR': 0.05, 'TEST_IHU_FACTOR': 0.1, 'TEST_LOT_SERIAL_FACTOR': 0.1, 'TEST_FOOD_PHARMA_FACTOR': 0.15, 'TEST_LOCATION_FACTOR': 0.1, 'TEST_SETUP_DATA_FIXED_HOURS': 1, 'TEST_SETUP_DATA_FACTOR': 0.1, 'TEST_MONITORED_FACTOR': 0.2, 'LABEL_TEST_FOOD_PHARMA_FACTOR': 0.1, 'LABEL_TEST_MONITORED_FACTOR': 0.1, 'DURATION_HOURS_PER_MONTH': 160, 'DURATION_FACTOR': 0.75, 'DEFAULT_LOW_FACTOR': 0.1, 'DEFAULT_HIGH_FACTOR': 0.25}
ENTITIES = ['Data Systems International, Inc. dba Cloud Inventory® ("Cloud Inventory")', 'Data Systems International (North America) Inc.', 'Data Systems International EMEA Ltd', 'Data Systems International Asia Pacific Pty. Ltd.', 'Data Systems International Holdings Pte Ltd.', 'DSI (Hong Kong) Limited', 'eNSYNC Solutions, Inc.']
CURRENCIES = ['Australian Dollar', 'British Pound', 'Canadian Dollar', 'Euro', 'New Zealand Dollar', 'US Dollar', 'ZZ1', 'ZZ2', 'ZZ3', 'ZZ4', 'ZZ5', 'ZZ6', 'ZZ7']
USER_COUNTS = [('USER_1', '1 to 50', 1, 4), ('USER_2', '51 to 100', 2, 6), ('USER_3', '101 to 250', 3, 8), ('USER_4', '250 to 500', 4, 12), ('USER_5', '501 to 1000', 5, 16), ('USER_6', 'Over 1000', 6, 20)]
GO_LIVE = [('NONE', 'None', 0, 0), ('REMOTE_ALL', 'Remote All', 32, 16), ('ON_SITE_ALL', 'On-Site All', 40, 24), ('ON_SITE_PRIMARY_REMOTE_OTHERS', 'On-Site Primary Remote Others', 40, 16)]
PROJECT_TYPES = [('CIP_CHANGE', 'CIP Change', 0), ('CIP_INSTALL', 'CIP Install', 8), ('EPP_CLOUD', 'EPP Cloud', 8), ('EPP_ON_PREM', 'EPP On Prem', 8), ('SMALL_PROJECT', 'Small Project', 0)]
DEPLOYED = [('JD_EDWARDS', 'JD Edwards', 16), ('NETSUITE', 'NetSuite', 18), ('NEXTWORLD', 'Nextworld', 20), ('OTHER', 'Other', 0), ('STANDALONE', 'Standalone', 0)]
CUSTOM = [('No Config', 0, 0), ('Simple', 16, 0.25), ('Moderate', 32, 0.75), ('Complex', 48, 1.0), ('Very Complex', 80, 1.25)]
REPORT = [('No Config', 0), ('Simple', 2), ('Moderate', 4), ('Complex', 8), ('Very Complex', 16)]

def _add(db, vid, category, key, label, number=None, text=None, value_type="text", parent=None, order=0, description=""):
    db.add(ConfigItem(config_version_id=vid, category=category, key=key, label=label,
        value_number=number, value_text=text, value_type=value_type, parent_key=parent,
        sort_order=order, active=True, description=description or None))

def seed_cip_database(db: Session):
    existing=(db.query(ConfigurationVersion).join(ConfigurationProduct,ConfigurationProduct.config_version_id==ConfigurationVersion.id)
        .filter(ConfigurationProduct.product_type==PRODUCT_CIP,ConfigurationVersion.status=="ACTIVE")
        .order_by(ConfigurationVersion.id.desc()).first())
    if existing: return existing
    v=ConfigurationVersion(name="CIP Estimate Model 2026.08.1",status="ACTIVE",
        change_reason="Approved CIP estimator model imported from Estimate_2026_CIP_06",
        activated_at=datetime.utcnow(),approval_status="ACTIVE")
    db.add(v); db.flush(); db.add(ConfigurationProduct(config_version_id=v.id,product_type=PRODUCT_CIP))
    for i,label in enumerate(["Install_Base","Net_New"]): _add(db,v.id,"CIP Customer Type",slug(label),label,value_type="catalog",order=i)
    for i,(k,l,h) in enumerate(PROJECT_TYPES): _add(db,v.id,"CIP Project Type",k,l,h,value_type="hours",order=i)
    for i,(k,l,n) in enumerate(DEPLOYED): _add(db,v.id,"CIP Deployed Over",k,l,n,value_type="number",order=i)
    for k,l,rank in RELEASES: _add(db,v.id,"CIP Release",k,l,rank,value_type="catalog",order=rank)
    for i,(k,l,m,p) in enumerate(USER_COUNTS): _add(db,v.id,"CIP User Count",k,l,p,json.dumps({"key":k,"label":l,"multiplier":m,"printer_hours":p}),"json",order=i)
    for i,(k,l,b,a) in enumerate(GO_LIVE): _add(db,v.id,"CIP Go Live",k,l,b,json.dumps({"base":b,"additional":a}),"json",order=i)
    for sites,mult in [(1,1),(2,1.75),(3,2.25)]: _add(db,v.id,"CIP UAT Site Multiplier",str(sites),str(sites),mult,value_type="number",order=sites)
    for i,label in enumerate(["None","LDAP","Okta","SAML"]): _add(db,v.id,"CIP Security Method",slug(label),label,0 if label=="None" else PARAMS["SSO_SETUP_HOURS"],value_type="hours",order=i)
    for i,label in enumerate(["No","On Prem","Cloud"]): _add(db,v.id,"CIP EPP Install",slug(label),label,value_type="catalog",order=i)
    for i,label in enumerate(["Planned","On Hold - Customer","On Hold - CI","Scheduled","WIP","Testing","Complete"]): _add(db,v.id,"Schedule Status",slug(label),label,value_type="catalog",order=i)
    for i,label in enumerate(CURRENCIES): _add(db,v.id,"Currency",slug(label),label,value_type="catalog",order=i)
    for i,label in enumerate(ENTITIES): _add(db,v.id,"Entity",f"CIP_ENTITY_{i+1}",label,value_type="catalog",order=i)
    for i,(label,hours) in enumerate([("No Config",0),("Baseline",0),("Mod Required",8)]): _add(db,v.id,"CIP Config Type",slug(label),label,hours,value_type="hours",order=i)
    for i,(label,hours,test) in enumerate(CUSTOM): _add(db,v.id,"CIP Custom Complexity",slug(label),label,hours,json.dumps({"test_factor":test}),"json",order=i)
    for i,(label,hours) in enumerate(REPORT): _add(db,v.id,"CIP Report Complexity",slug(label),label,hours,value_type="hours",order=i)
    for i,(k,val) in enumerate(PARAMS.items()): _add(db,v.id,"CIP Parameter",k,k.replace("_"," ").title(),val,value_type="number",order=i)
    int_hours=[2,3,4]+[1]*(len(INTEGRATIONS)-3)
    for release_key,release_label,rank in RELEASES:
        for i,label in enumerate(DESKTOP):
            k=f"{release_key}:{slug(label)}"; _add(db,v.id,"CIP Desktop Application",k,label,.25,json.dumps({"test_factor":.75}),"json",release_key,i)
        for i,label in enumerate(MOBILE):
            k=f"{release_key}:{slug(label)}"; _add(db,v.id,"CIP Mobile Application",k,label,1,json.dumps({"test_factor":.75}),"json",release_key,i)
        for i,(label,hours) in enumerate(zip(INTEGRATIONS,int_hours)):
            k=f"{release_key}:{slug(label)}"; _add(db,v.id,"CIP Integration",k,label,hours,json.dumps({"test_factor":.75}),"json",release_key,i)
    db.commit(); return v

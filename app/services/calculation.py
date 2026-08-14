from __future__ import annotations
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable
from sqlalchemy.orm import Session
from ..models import (EstimateRevision, ConfigItem, DetailAdjustment, CalculationAdjustment,
                      EstimateApplication, EstimateCustomApplication)

ENGINE_VERSION = "1.0.0"

def xrnd(value: float, digits: int = 0) -> float:
    q = Decimal("1") if digits == 0 else Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))

class Config:
    def __init__(self, db: Session, version_id: int):
        self.items = db.query(ConfigItem).filter(ConfigItem.config_version_id == version_id).all()
        self.by_cat = {}
        self.by_key = {}
        for item in self.items:
            self.by_cat.setdefault(item.category, []).append(item)
            self.by_key[(item.category,item.key)] = item
        for values in self.by_cat.values(): values.sort(key=lambda x:(x.sort_order,x.label))

    def param(self, key: str) -> float:
        for i in self.by_cat.get("Project Factors",[])+self.by_cat.get("Testing",[])+self.by_cat.get("Plan",[])+self.by_cat.get("Install",[])+self.by_cat.get("Design",[])+self.by_cat.get("Build",[])+self.by_cat.get("Test",[])+self.by_cat.get("Go Live",[])+self.by_cat.get("Summary",[])+self.by_cat.get("EPP",[])+self.by_cat.get("Development",[])+self.by_cat.get("Upgrade",[]):
            if i.key == key: return float(i.value_number or 0)
        for i in self.items:
            if i.key == key and i.value_number is not None: return float(i.value_number)
        raise KeyError(f"Required configuration parameter missing: {key}")

    def value_by_label(self, category: str, label: str) -> float:
        for i in self.by_cat.get(category,[]):
            if i.label.strip().casefold() == (label or "").strip().casefold():
                return float(i.value_number or 0)
        raise KeyError(f"Required configuration lookup missing: {category} / {label}")

    def item_by_label(self, category: str, label: str):
        for i in self.by_cat.get(category,[]):
            if i.label.strip().casefold() == (label or "").strip().casefold(): return i
        return None

    def json_by_label(self, category: str, label: str):
        import json
        i=self.item_by_label(category,label)
        if not i or not i.value_text: return {}
        try: return json.loads(i.value_text)
        except Exception: return {}

@dataclass
class DetailLine:
    key: str
    section: str
    ref: str
    definition: str
    base_hours: float
    mod_hours: float
    dev_subtotal: float
    unit_testing: float
    notes: str
    total: float
    error: str = ""

@dataclass
class CalcLine:
    key: str
    phase: str
    description: str
    standard_hours: float
    adjust_hours: float
    extended_hours: float
    adjust_notes: str = ""
    trace: str = ""


def unit_test(hours: float, factor: float) -> float:
    v = hours * factor
    if v == 0: return 0.0
    if v < 1: return 1.0
    return xrnd(v)


def detail_calculation(db: Session, rev: EstimateRevision):
    cfg=Config(db,rev.config_version_id)
    factor = rev.unit_test_factor_override if rev.unit_test_factor_override is not None else cfg.param("UNIT_TEST_FACTOR")
    adjusts={a.line_key:a for a in db.query(DetailAdjustment).filter(DetailAdjustment.revision_id==rev.id).all()}
    lines=[]
    summaries={}

    def add(key,section,ref,definition,base,error=""):
        adj=adjusts.get(key)
        mod=float(adj.mod_hours if adj else 0)
        notes=adj.notes if adj else ""
        desc=(adj.description.strip() if adj and adj.description else definition)
        dev=float(base)+mod
        ut=unit_test(dev,factor)
        total=dev+ut
        lines.append(DetailLine(key,section,str(ref),desc,float(base),mod,dev,ut,notes,total,error))

    # Upgrade definition.
    upgrade_base=0.0
    if rev.upgrade_app_count>0 and rev.upgrade_type:
        uf=cfg.value_by_label("Upgrade Type",rev.upgrade_type)
        count=rev.upgrade_app_count + (rev.upgrade_app_count*cfg.param("UPGRADE_ANDROID_FACTOR") if rev.android_change else 0)
        upgrade_base=uf*count
    uadj=adjusts.get("UPGRADE")
    umod=float(uadj.mod_hours if uadj else 0)
    udev=(cfg.param("UPGRADE_FIXED_DEV_HOURS")+upgrade_base+umod) if (upgrade_base+umod)>0 else 0
    uut=unit_test(udev,factor)
    lines.append(DetailLine("UPGRADE","Upgrade Definition","1",f"Upgrade App Count - {rev.upgrade_app_count}",upgrade_base,umod,udev,uut,uadj.notes if uadj else "",udev+uut))

    apps=db.query(EstimateApplication).filter(EstimateApplication.revision_id==rev.id,EstimateApplication.kind=="APPLICATION").order_by(EstimateApplication.sort_order).all()
    for idx,a in enumerate(apps,2):
        base=cfg.value_by_label("Application Effort",a.config_type)
        err="No modification hours expected for No Config/Baseline" if a.config_type in ("No Config","Baseline") and adjusts.get(f"APP:{a.catalog_key}") and adjusts[f"APP:{a.catalog_key}"].mod_hours else ""
        add(f"APP:{a.catalog_key}","Baseline Applications",idx,a.label,base,err)
    packages=db.query(EstimateApplication).filter(EstimateApplication.revision_id==rev.id,EstimateApplication.kind=="PACKAGE").order_by(EstimateApplication.sort_order).all()
    for idx,a in enumerate(packages,37): add(f"PKG:{a.catalog_key}","Baseline Packages",idx,a.label,cfg.value_by_label("Package Effort",a.config_type))
    customs=db.query(EstimateCustomApplication).filter(EstimateCustomApplication.revision_id==rev.id).order_by(EstimateCustomApplication.sort_order).all()
    for idx,a in enumerate(customs,1):
        if not a.description and a.complexity=="No Config": continue
        add(f"CUSTOM:{a.id}","Custom Applications",idx,a.description,cfg.value_by_label("Custom Effort",a.complexity) if a.description else 0)
    for idx in range(1,max(rev.label_count,0)+1): add(f"LABEL:{idx}","Labels",idx,"",cfg.param("LABEL_BASE_HOURS"))
    for idx in range(1,max(rev.iot_count,0)+1): add(f"IOT:{idx}","IoT Service Definitions",idx,"",cfg.param("IOT_SERVICE_DEF_HOURS"))
    for idx in range(1,max(rev.erp_integration_count,0)+1): add(f"ERPINT:{idx}","ERP Service Definitions",idx,"",cfg.param("ERP_SERVICE_DEF_HOURS"))
    for idx in range(1,max(rev.data_rep_count,0)+1): add(f"DATAREP:{idx}","Data Replication Sessions",idx,"",cfg.param("DATA_REP_SESSION_HOURS"))

    for section in ["Upgrade Definition","Baseline Applications","Baseline Packages","Custom Applications","Labels","IoT Service Definitions","ERP Service Definitions","Data Replication Sessions"]:
        sl=[x for x in lines if x.section==section]
        summaries[section]={
            "count":sum(1 for x in sl if (x.base_hours>0 or x.mod_hours!=0)),
            "base":sum(x.base_hours for x in sl), "mod":sum(x.mod_hours for x in sl),
            "dev":sum(x.dev_subtotal for x in sl), "unit":sum(x.unit_testing for x in sl), "total":sum(x.total for x in sl),
        }
    return lines,summaries,factor


def calculation(db: Session, rev: EstimateRevision):
    cfg=Config(db,rev.config_version_id)
    details,summ,unit_factor=detail_calculation(db,rev)
    adjustments={a.line_key:a for a in db.query(CalculationAdjustment).filter(CalculationAdjustment.revision_id==rev.id).all()}
    result={}
    def adj(key):
        a=adjustments.get(key); return (float(a.adjust_hours),a.notes) if a else (0.0,"")
    def put(key,phase,desc,std,trace="",extended_mode="direct"):
        a,n=adj(key)
        ext=std+a
        result[key]=CalcLine(key,phase,desc,xrnd(std),a,xrnd(ext),n,trace)
        return result[key]
    def ext(key): return result[key].extended_hours
    def std(key): return result[key].standard_hours

    small=rev.project_type=="Small Project"
    im=cfg.param("SMALL_PROJECT_IM_FACTOR" if small else "STANDARD_IM_FACTOR")
    prep=cfg.param("SMALL_PROJECT_PREP_FACTOR" if small else "STANDARD_PREP_FACTOR")
    contingency=cfg.param("SMALL_PROJECT_CONTINGENCY" if small else "STANDARD_CONTINGENCY")
    markup=cfg.value_by_label("Delivery Method",rev.delivery_method)
    solution=cfg.json_by_label("Solution Type",rev.project_type)
    app_count=sum(1 for a in rev.applications if a.config_type in ("Baseline","Baseline_4","Mod Required"))
    package_count=sum(1 for a in rev.applications if a.kind=="PACKAGE" and a.config_type!="No Config")
    baseline_count=sum(1 for a in rev.applications if a.kind=="APPLICATION" and a.config_type.startswith("Baseline"))
    mod_count=sum(1 for a in rev.applications if a.kind=="APPLICATION" and a.config_type=="Mod Required")
    custom_count=sum(1 for a in rev.custom_apps if a.description and a.complexity!="No Config")
    standard_total=app_count+package_count  # Workbook Estimate!L26 = baseline + modified + package selections.
    component_count=standard_total+custom_count+rev.label_count+rev.iot_count+rev.erp_integration_count
    detail_dev=lambda sec: summ.get(sec,{}).get("dev",0)
    detail_unit=lambda sec: summ.get(sec,{}).get("unit",0)
    detail_total=lambda sec: summ.get(sec,{}).get("total",0)
    detail_count=lambda sec: summ.get(sec,{}).get("count",0)

    # Build direct lines first because Plan, Design and Test contain formulas referencing Build values.
    put("BUILD_APP_DEV_TRAINING","Build","Application Developer Training (opt-in)" if rev.app_dev_training else "Not Included - Application Developer Training (did not opt-in)",cfg.param("APP_DEV_TRAINING_HOURS") if rev.app_dev_training else 0)
    put("BUILD_STANDARD_APPS","Build","Standard App - FastForm Setup, App Configure",detail_dev("Baseline Applications"))
    put("BUILD_STANDARD_PACKAGES","Build","Standard Packages - Setup, Data Rep, Configure",detail_dev("Baseline Packages"))
    put("BUILD_CUSTOM_APPS","Build","Custom Applications Development / Configure",detail_dev("Custom Applications"))
    put("BUILD_LABELS","Build","Labels Develop / Validate",detail_dev("Labels"))
    put("BUILD_EPP_INTEGRATION","Build","EPP Only Project EPP Integration",cfg.value_by_label("EPP Integration",rev.epp_integration))
    put("BUILD_IOT","Build","IOT Interfaces",detail_dev("IoT Service Definitions"))
    put("BUILD_ERP_INTEGRATION","Build","ERP Integration Development / Configure",detail_dev("ERP Service Definitions"))
    put("BUILD_DATA_REP","Build","Setup / Configure Data Replication Session",detail_total("Data Replication Sessions"))
    put("BUILD_UPGRADE","Build","Upgrade App Conversion Hours",detail_dev("Upgrade Definition"))
    uc=cfg.json_by_label("User Count",rev.user_count)
    put("BUILD_HANDHELD_SETUP","Build","Handheld / Desktop Client Setup",0 if small else float(uc.get("handheld_setup_hours",0)))
    put("BUILD_PRINTER_SETUP","Build","Printer Setup",0 if rev.epp_install=="No" else float(uc.get("printer_setup_hours",0)))
    put("BUILD_UNIT_TEST_DATA","Build","Setup Unit Test Data",detail_count("Data Replication Sessions"))
    build_units=sum(detail_unit(s) for s in ["Upgrade Definition","Baseline Applications","Baseline Packages","Custom Applications","Labels","IoT Service Definitions","ERP Service Definitions"])
    put("BUILD_UNIT_TESTING","Build","Unit Testing & QA",build_units)
    put("BUILD_ADMIN_TRAINING","Build","Admin Setup User / Roles Training",cfg.param("ADMIN_TRAINING_NET_NEW_HOURS") if rev.customer_type=="Net_New" else 0)
    put("BUILD_PACEJET_VALIDATION","Build","Pacejet Solution Validation",cfg.param("PACEJET_VALIDATION_HOURS") if rev.pacejet else 0)
    demo=xrnd((standard_total+custom_count)*cfg.param("APP_DEMO_HOURS_PER_APP"))
    put("BUILD_APP_DEMOS","Build","Application Demonstrations",demo)
    put("BUILD_REMEDIATION","Build","Application Remediation Review",xrnd(demo*cfg.param("APP_REMEDIATION_FACTOR")))
    put("BUILD_WORKSHOP","Build","Solution Workshop / Conference Room Pilot and Train the Trainer",xrnd(demo*cfg.param("SOLUTION_WORKSHOP_FACTOR")))
    # Promotion validation depends on adjusted development lines and Plan base-package install, which is known directly.
    plan_base_package=cfg.param("BASE_APP_PACKAGE_INSTALL_HOURS") if standard_total>0 else 0
    plan_base_package_ext=plan_base_package + adj("PLAN_BASE_PACKAGE")[0]
    promotion_base=xrnd((sum(ext(k) for k in ["BUILD_STANDARD_APPS","BUILD_STANDARD_PACKAGES","BUILD_CUSTOM_APPS","BUILD_LABELS","BUILD_EPP_INTEGRATION","BUILD_IOT","BUILD_ERP_INTEGRATION","BUILD_DATA_REP","BUILD_UPGRADE"])+plan_base_package_ext)*cfg.param("PROMOTION_VALIDATION_FACTOR"))
    put("BUILD_PROMOTION","Build","Application Promotion & Stage Environment Validation",promotion_base)

    # Design direct calculations.
    approve_scripts=0 if rev.write_test_scripts else xrnd((mod_count+package_count+custom_count)*cfg.param("CUSTOMER_TEST_SCRIPT_FACTOR"))
    put("DESIGN_APPROVE_TEST_SCRIPTS","Design","Approve Customer Test Scripts",approve_scripts)
    ci_scripts=xrnd(sum(ext(k) for k in ["BUILD_STANDARD_APPS","BUILD_STANDARD_PACKAGES","BUILD_CUSTOM_APPS","BUILD_LABELS","BUILD_EPP_INTEGRATION","BUILD_IOT","BUILD_ERP_INTEGRATION"])*cfg.param("CI_TEST_SCRIPT_FACTOR")) if rev.write_test_scripts else 0
    put("DESIGN_CI_TEST_SCRIPTS","Design","CI to Write Test Scripts (opt-in)" if rev.write_test_scripts else "Not Included - CI to Write Test Scripts (did not opt-in)",ci_scripts)
    put("DESIGN_INTERNAL_REVIEW","Design","Internal Solution Design Review",cfg.param("INTERNAL_DESIGN_REVIEW_HOURS") if (mod_count+custom_count)>0 else 0)
    sol_design=xrnd(sum(std(k) for k in ["BUILD_STANDARD_APPS","BUILD_STANDARD_PACKAGES","BUILD_CUSTOM_APPS","BUILD_LABELS","BUILD_EPP_INTEGRATION","BUILD_IOT","BUILD_ERP_INTEGRATION"])*cfg.param("SOLUTION_DESIGN_FACTOR"))
    put("DESIGN_SOLUTION","Design","Solution Design",sol_design)

    # Test direct calculations.
    put("TEST_END_USER_DOC","Test","Develop End User Documentation (opt-in)" if rev.end_user_documentation else "Not Included - Develop End User Documentation (did not opt-in)",(standard_total+custom_count)*cfg.param("END_USER_DOC_HOURS_PER_APP") if rev.end_user_documentation else 0)
    put("TEST_END_USER_TRAINING","Test","CI Led End User Training (opt-in)" if rev.end_user_training else "Not Included - CI Led End User Training (did not opt-in)",(standard_total+custom_count)*float(uc.get("multiplier",0)) if rev.end_user_training else 0)
    put("TEST_UAT_PREP","Test","User Acceptance Testing (UAT) Prep Session",0 if small else cfg.param("UAT_PREP_STANDARD_HOURS"))
    put("TEST_UAT_DATA","Test","UAT Data Setup",detail_count("Data Replication Sessions"))
    uat_mult=cfg.value_by_label("UAT Site Multiplier",str(max(1,min(3,rev.uat_sites))))
    build_scope=sum(ext(k) for k in ["BUILD_STANDARD_APPS","BUILD_STANDARD_PACKAGES","BUILD_CUSTOM_APPS","BUILD_LABELS","BUILD_EPP_INTEGRATION","BUILD_IOT","BUILD_ERP_INTEGRATION","BUILD_DATA_REP","BUILD_UPGRADE"])
    uat=xrnd(build_scope*rev.base_test_pct*uat_mult)
    put("TEST_UAT_1","Test","User Acceptance Testing (UAT) & Issue Remediation",uat)
    put("TEST_UAT_2","Test","User Acceptance Testing (UAT) & Issue Remediation 2",uat if rev.test_cycles>=2 else 0)
    put("TEST_UAT_3","Test","User Acceptance Testing (UAT) & Issue Remediation 3",uat if rev.test_cycles>=3 else 0)
    put("TEST_LOAD","Test","Platform Limited Load Test",float(solution.get("load_test_effort",0)))
    count_sum=(detail_count("Upgrade Definition") + detail_count("Baseline Applications")*2 + detail_count("Baseline Packages") + detail_count("Custom Applications") + detail_count("Labels") + detail_count("IoT Service Definitions") + detail_count("ERP Service Definitions"))
    put("TEST_READINESS","Test","Go-Live Readiness Assessment",xrnd(count_sum*cfg.param("LOAD_TEST_FACTOR")))
    put("TEST_PROD_VALIDATION","Test","Go-Live Prep & Production Validation Testing",xrnd(count_sum*cfg.param("GO_LIVE_PREP_VALIDATION_FACTOR")))

    # Go-Live direct calculations.
    gl_prep=xrnd(sum(ext(k) for k in ["BUILD_STANDARD_APPS","BUILD_CUSTOM_APPS","BUILD_LABELS","BUILD_IOT","BUILD_UPGRADE"])*cfg.param("GO_LIVE_PREP_FACTOR"))
    put("GO_LIVE_PREP","Go Live","Go-Live Prep Meeting",gl_prep)
    sites=max(rev.go_live_sites,0)
    support=0
    if rev.go_live_type=="Remote All" and sites>0: support=cfg.param("GO_LIVE_REMOTE_BASE_HOURS")+max(0,sites-1)*cfg.param("GO_LIVE_REMOTE_EXTRA_SITE_HOURS")
    elif rev.go_live_type=="On-Site All" and sites>0: support=cfg.param("GO_LIVE_ONSITE_BASE_HOURS")+max(0,sites-1)*cfg.param("GO_LIVE_ONSITE_EXTRA_SITE_HOURS")
    elif rev.go_live_type=="On-Site Primary Remote Others" and sites>0: support=cfg.param("GO_LIVE_ONSITE_BASE_HOURS")+max(0,sites-1)*cfg.param("GO_LIVE_HYBRID_EXTRA_SITE_HOURS")
    put("GO_LIVE_SUPPORT","Go Live","Go-Live Support",support)

    # Plan direct lines. Some are based on component counts and Build standard effort.
    kickoff=cfg.param("PROJECT_KICKOFF_NET_NEW_HOURS") if rev.customer_type=="Net_New" else (cfg.param("PROJECT_KICKOFF_SMALL_HOURS") if small else cfg.param("PROJECT_KICKOFF_STANDARD_HOURS"))
    put("PLAN_KICKOFF","Plan","Project Kickoff Meeting",kickoff)
    put("PLAN_ADW","Plan","Architecture Design Workshop (ADW) & Architecture Design Document (ADD)",float(solution.get("adw_hours",0)))
    mep_install=0 if rev.project_type.startswith("EPP") else float(solution.get("on_prem_hours",0))+(cfg.param("HA_INSTALL_INCREMENT_HOURS") if rev.high_availability else 0)
    put("PLAN_MEP_INSTALL","Plan","MEP Cloud Installation" if solution.get("cloud_flag") else "MEP On-Premise Installation",mep_install)
    put("PLAN_EPP_INSTALL","Plan","Enterprise Printing Platform Installation",cfg.param("EPP_ON_PREM_INSTALL_HOURS") if rev.epp_install=="On Prem" else 0)
    put("PLAN_PRINT_BRIDGE","Plan","EPP Print Bridge Installation",cfg.param("PRINT_BRIDGE_INSTALL_HOURS")*max(0,rev.label_sites-1) if rev.epp_install!="No" else 0)
    put("PLAN_GATEWAY","Plan","Gateway Installation",cfg.param("GATEWAY_INSTALL_HOURS") if rev.gateway else 0)
    put("PLAN_SSO","Plan","SSO Setup / Configure",cfg.value_by_label("Security Method",rev.security_method) if rev.security_method!="None" else 0)
    put("PLAN_BASE_PACKAGE","Plan","Base Application Package Install",plan_base_package)
    put("PLAN_FACILITY","Plan","Customer Facility Review",cfg.param("CUSTOMER_FACILITY_REVIEW_HOURS") if rev.customer_type=="Net_New" else 0)
    put("PLAN_ACCESS","Plan","Confirm VPN & ERP Accesss",(cfg.param("ACCESS_CONFIRMATION_HOURS") if rev.consultant_access_setup else 0)+(cfg.param("ACCESS_CONFIRMATION_HOURS") if rev.onboarding else 0))
    put("PLAN_PACEJET","Plan","Pacejet Requirements Session",cfg.param("PACEJET_REQUIREMENTS_HOURS") if rev.pacejet else 0)
    put("PLAN_ORIENTATION_PREP","Plan","Solution Orientation Prep",standard_total)
    count_basis=sum(detail_count(s) for s in ["Baseline Applications","Baseline Packages","Custom Applications","Labels","IoT Service Definitions","ERP Service Definitions"])
    orient=(xrnd(count_basis*cfg.param("SOLUTION_ORIENTATION_FACTOR_1"))+xrnd(count_basis*cfg.param("SOLUTION_ORIENTATION_FACTOR_2"))) if standard_total>0 else 0
    put("PLAN_ORIENTATION","Plan","Solution Orientation Session",orient)
    put("PLAN_GAP","Plan","Gap Analysis",xrnd(count_basis*cfg.param("GAP_ANALYSIS_FACTOR")) if component_count>0 else 0)
    brd=xrnd(sum(std(k) for k in ["BUILD_STANDARD_APPS","BUILD_STANDARD_PACKAGES","BUILD_CUSTOM_APPS","BUILD_LABELS","BUILD_EPP_INTEGRATION","BUILD_IOT","BUILD_ERP_INTEGRATION"])*cfg.param("BRD_FACTOR")) if component_count>0 else 0
    put("PLAN_BRD","Plan","Business Requirement Document (BRD) Creation & Review Sessions",brd)

    # Phase wrappers calculate standard from standard children and extended from adjusted child values.
    phase_children={
      "Plan":["PLAN_KICKOFF","PLAN_ADW","PLAN_MEP_INSTALL","PLAN_EPP_INSTALL","PLAN_PRINT_BRIDGE","PLAN_GATEWAY","PLAN_SSO","PLAN_BASE_PACKAGE","PLAN_FACILITY","PLAN_ACCESS","PLAN_PACEJET","PLAN_ORIENTATION_PREP","PLAN_ORIENTATION","PLAN_GAP","PLAN_BRD"],
      "Design":["DESIGN_APPROVE_TEST_SCRIPTS","DESIGN_CI_TEST_SCRIPTS","DESIGN_INTERNAL_REVIEW","DESIGN_SOLUTION"],
      "Build":["BUILD_APP_DEV_TRAINING","BUILD_STANDARD_APPS","BUILD_STANDARD_PACKAGES","BUILD_CUSTOM_APPS","BUILD_LABELS","BUILD_EPP_INTEGRATION","BUILD_IOT","BUILD_ERP_INTEGRATION","BUILD_DATA_REP","BUILD_UPGRADE","BUILD_HANDHELD_SETUP","BUILD_PRINTER_SETUP","BUILD_UNIT_TEST_DATA","BUILD_UNIT_TESTING","BUILD_ADMIN_TRAINING","BUILD_PACEJET_VALIDATION","BUILD_APP_DEMOS","BUILD_REMEDIATION","BUILD_WORKSHOP","BUILD_PROMOTION"],
      "Test":["TEST_END_USER_DOC","TEST_END_USER_TRAINING","TEST_UAT_PREP","TEST_UAT_DATA","TEST_UAT_1","TEST_UAT_2","TEST_UAT_3","TEST_LOAD","TEST_READINESS","TEST_PROD_VALIDATION"],
      "Go Live":["GO_LIVE_PREP","GO_LIVE_SUPPORT"]}
    for phase,children in phase_children.items():
        pkey=phase.upper().replace(" ","_")
        child_std=sum(std(k) for k in children); child_ext=sum(ext(k) for k in children)
        # Project management: workbook treats adjustment as an input to the factor rather than a direct add.
        a,n=adj(f"{pkey}_PM")
        pm_std=xrnd(child_std*im); pm_ext=xrnd((child_ext+a)*im)
        result[f"{pkey}_PM"]=CalcLine(f"{pkey}_PM",phase,f"{phase} Project Management",pm_std,a,pm_ext,n,f"ROUND(child hours × {im:.1%})")
        a2,n2=adj(f"{pkey}_CONTINGENCY")
        cont_std=xrnd(child_std*contingency + child_std*markup)
        cont_ext=a2+xrnd(child_ext*contingency + child_ext*markup)
        result[f"{pkey}_CONTINGENCY"]=CalcLine(f"{pkey}_CONTINGENCY",phase,f"{phase} Contingency",cont_std,a2,xrnd(cont_ext),n2,f"Contingency {contingency:.1%} + delivery markup {markup:.1%}")
        if phase=="Plan":
            a3,n3=adj("PLAN_PREP")
            prep_std=xrnd(child_std*prep); result["PLAN_PREP"]=CalcLine("PLAN_PREP","Plan","Project preparation and setup",prep_std,a3,xrnd(prep_std+a3),n3,f"ROUND(child hours × {prep:.1%})")
    # Ordered workbook-like output.
    order=[]
    phase_defs=[
      ("Plan",["PLAN_PM","PLAN_CONTINGENCY","PLAN_PREP"]+phase_children["Plan"]),
      ("Design",["DESIGN_PM","DESIGN_CONTINGENCY"]+phase_children["Design"]),
      ("Build",["BUILD_PM","BUILD_CONTINGENCY"]+phase_children["Build"]),
      ("Test",["TEST_PM","TEST_CONTINGENCY"]+phase_children["Test"]),
      ("Go Live",["GO_LIVE_PM","GO_LIVE_CONTINGENCY"]+phase_children["Go Live"]),
    ]
    totals={}
    for phase,keys in phase_defs:
        pls=[result[k] for k in keys]
        totals[phase]={"standard":sum(x.standard_hours for x in pls),"extended":sum(x.extended_hours for x in pls)}
        order.extend(pls)
    total=xrnd(sum(t["extended"] for t in totals.values()))
    fees=total*rev.billing_rate
    low_factor=cfg.param("LOW_RANGE_FACTOR")
    high_factor=cfg.param("HIGH_RANGE_FACTOR")
    low=xrnd(total-(total*low_factor)); high=xrnd(total*(1+high_factor))
    duration=xrnd((total/cfg.param("ESTIMATE_DURATION_HOURS_PER_MONTH"))*cfg.param("ESTIMATE_DURATION_UTILIZATION"),2) if total else 0
    summary={"hours":total,"fees":fees,"low_hours":low,"low_fees":fees-(fees*low_factor),"high_hours":high,"high_fees":fees*(1+high_factor),"duration_months":duration,"unit_test_factor":unit_factor,"phase_totals":totals,"markup":markup,"low_factor":low_factor,"high_factor":high_factor}
    return order,summary,details,summ


def recalculate_and_store(db: Session, rev: EstimateRevision):
    lines,summary,details,summ=calculation(db,rev)
    rev.calculated_hours=summary["hours"]; rev.calculated_fees=summary["fees"]
    rev.low_hours=summary["low_hours"]; rev.high_hours=summary["high_hours"]; rev.duration_months=summary["duration_months"]
    rev.engine_version=ENGINE_VERSION
    db.flush()
    return lines,summary,details,summ

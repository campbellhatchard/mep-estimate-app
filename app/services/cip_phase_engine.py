from __future__ import annotations

from typing import Iterable
from sqlalchemy.orm import Session

from ..cip_models import CIPNonBillableAllocation, CIPRevisionInput
from ..models import CalculationAdjustment, EstimateRevision
from .cip_detail_engine import CIPCalcLine, CIPConfig, CIPDetailLine, detail_calculation, xrnd


def calculation(db: Session, rev: EstimateRevision):
    inp = db.get(CIPRevisionInput, rev.id)
    if not inp:
        raise KeyError(f"CIP inputs missing for revision {rev.id}")
    cfg = CIPConfig(db, rev.config_version_id)
    details, detail_summary = detail_calculation(db, rev)
    calc_adjustments = {x.line_key: x for x in db.query(CalculationAdjustment).filter(CalculationAdjustment.revision_id == rev.id).all()}
    nonbill = {x.line_key: x for x in db.query(CIPNonBillableAllocation).filter(CIPNonBillableAllocation.revision_id == rev.id).all()}
    result: dict[str, CIPCalcLine] = {}

    def put(key: str, phase: str, desc: str, standard: float, trace: str = "", allow_nonbillable: bool = False):
        adj = calc_adjustments.get(key)
        adjust = float(adj.adjust_hours if adj else 0)
        invest = float(standard) + adjust
        nballoc = nonbill.get(key) if allow_nonbillable else None
        nb_hours = float(nballoc.hours if nballoc else 0)
        result[key] = CIPCalcLine(key, phase, desc, float(standard), adjust, invest, nb_hours,
            invest + nb_hours, adj.notes if adj else "", nballoc.notes if nballoc else "", trace)
        return result[key]

    def std(key): return result[key].standard_hours
    def inv(key): return result[key].investment_hours
    def nb(key): return result[key].non_billable_hours
    def detail_rows(section): return [x for x in details if x.section == section]
    def selected_count(section): return sum(1 for x in detail_rows(section) if x.base_hours > 0)

    desktop_std_count = selected_count("Desktop Applications")
    desktop_custom_count = selected_count("Custom Desktop Applications")
    mobile_std_count = selected_count("Mobile Applications")
    mobile_custom_count = selected_count("Custom Mobile Applications")
    report_count = selected_count("Reporting Development")
    integration_count = selected_count("Baseline Integrations")
    component_count = sum(selected_count(section) for section in [
        "Desktop Applications", "Custom Desktop Applications", "Mobile Applications",
        "Custom Mobile Applications", "Reporting Development", "Labels", "Baseline Integrations",
        "Custom Boomi Integrations", "RESTful Interfaces",
    ])
    demo_component_count = desktop_std_count + desktop_custom_count + mobile_std_count + mobile_custom_count + report_count
    solution_testing_total = sum(x.testing_total for x in details)

    desktop_baseline_dev = sum(x.development_hours for x in detail_rows("Desktop Applications") if x.test_class == 1)
    desktop_mod_dev = sum(x.development_hours for x in detail_rows("Desktop Applications") if x.test_class == 2)
    mobile_baseline_dev = sum(x.development_hours for x in detail_rows("Mobile Applications") if x.test_class == 1)
    mobile_mod_dev = sum(x.development_hours for x in detail_rows("Mobile Applications") if x.test_class == 2)
    custom_desktop_dev = sum(x.development_hours for x in detail_rows("Custom Desktop Applications"))
    custom_mobile_dev = sum(x.development_hours for x in detail_rows("Custom Mobile Applications"))
    report_dev = sum(x.development_hours for x in detail_rows("Reporting Development"))
    label_dev = sum(x.development_hours for x in detail_rows("Labels"))
    integration_dev = sum(x.development_hours for x in detail_rows("Baseline Integrations"))
    boomi_dev = sum(x.development_hours for x in detail_rows("Custom Boomi Integrations"))
    rest_service_dev = sum(x.development_hours for x in detail_rows("RESTful Interfaces"))
    rest_app_dev = sum(x.application_integration_hours for x in detail_rows("RESTful Interfaces"))
    unit_testing = sum(x.unit_testing for x in details)

    put("BUILD_SSO", "Build", "SSO Setup", 0 if inp.security_method == "None" else cfg.param("SSO_SETUP_HOURS"))
    put("BUILD_MOBILE_DEV_TRAINING", "Build", "Mobile Application Developer Training (opt-in)", cfg.param("MOBILE_DEV_TRAINING_HOURS") if inp.mobile_dev_training else 0)
    put("BUILD_CIP_DESKTOP_DEV_TRAINING", "Build", "CIP Desktop Application Developer Training (opt-in)", cfg.param("CIP_DESKTOP_DEV_TRAINING_HOURS") if inp.cip_desktop_dev_training else 0)
    module_hours = cfg.param("MODULE_SETTINGS_INSTALL_BASE_HOURS") if rev.customer_type == "Install_Base" else cfg.param("MODULE_SETTINGS_NET_NEW_HOURS")
    put("BUILD_MODULE_SETTINGS", "Build", "Update Module Settings & Config based on BRD", module_hours)
    put("BUILD_DESKTOP_BASELINE", "Build", "Desktop Standard Baseline Apps", desktop_baseline_dev)
    put("BUILD_DESKTOP_MOD", "Build", "Desktop Standard Mod Required Apps", desktop_mod_dev)
    put("BUILD_DESKTOP_CUSTOM", "Build", "Desktop Custom Apps", custom_desktop_dev)
    put("BUILD_MOBILE_BASELINE", "Build", "Mobile App Baseline Apps", mobile_baseline_dev)
    put("BUILD_MOBILE_MOD", "Build", "Mobile App Mod Required App", mobile_mod_dev)
    put("BUILD_MOBILE_CUSTOM", "Build", "Mobile Custom Apps", custom_mobile_dev)
    put("BUILD_REPORTING", "Build", "CIP Reporting Development", report_dev)
    put("BUILD_LABELS", "Build", "EPP Labels Develop / Validate", label_dev)
    put("BUILD_STANDARD_BOOMI", "Build", "Standard Boomi Interface Configuration", integration_dev)
    put("BUILD_CUSTOM_BOOMI", "Build", "Custom Boomi Integration Development", boomi_dev)
    put("BUILD_REST_SERVICE", "Build", "RESTful Interface Service Definition Development", rest_service_dev)
    put("BUILD_REST_APP_INTEGRATION", "Build", "RESTful Interface Service Definition Application Integration Effort", rest_app_dev)
    user_meta = cfg.json_item(cfg.item_by_label("CIP User Count", inp.user_count))
    put("BUILD_PRINTER_DEVICE", "Build", "Printer/Device Setup & Training", float(user_meta.get("printer_hours", 0)) if rev.customer_type == "Net_New" else 0)
    put("BUILD_DASHBOARD", "Build", "Baseline Dashboard Configuration", cfg.param("BASELINE_DASHBOARD_HOURS") if rev.customer_type == "Net_New" else 0)
    put("BUILD_UNIT_TESTING", "Build", "Unit Testing & QA", unit_testing)
    put("BUILD_ADMIN_TRAINING", "Build", "Admin Setup User / Roles Training", cfg.param("ADMIN_TRAINING_HOURS") if rev.customer_type == "Net_New" else 0)
    put("BUILD_PACEJET_VALIDATION", "Build", "3G PaceJet Solution Validation", cfg.param("PACEJET_VALIDATION_HOURS") if inp.pacejet else 0)
    demos = xrnd(demo_component_count * cfg.param("APP_DEMO_HOURS_PER_APP"), 0)
    put("BUILD_DEMOS", "Build", "Application Demonstrations", demos)
    put("BUILD_REMEDIATION", "Build", "Application Remediation Review", xrnd(demos * cfg.param("APP_REMEDIATION_FACTOR"), 0))
    put("BUILD_WORKSHOP", "Build", "Solution Workshop / Conference Room Pilot and Train the Trainer", xrnd(demos * cfg.param("SOLUTION_WORKSHOP_FACTOR"), 0))
    build_scope_keys = [
        "BUILD_DESKTOP_BASELINE", "BUILD_DESKTOP_MOD", "BUILD_DESKTOP_CUSTOM", "BUILD_MOBILE_BASELINE",
        "BUILD_MOBILE_MOD", "BUILD_MOBILE_CUSTOM", "BUILD_REPORTING", "BUILD_LABELS", "BUILD_STANDARD_BOOMI",
        "BUILD_CUSTOM_BOOMI", "BUILD_REST_SERVICE", "BUILD_REST_APP_INTEGRATION",
    ]
    build_scope_investment = sum(inv(k) for k in build_scope_keys)
    metadata_raw = xrnd(build_scope_investment * cfg.param("METADATA_MIGRATION_FACTOR"), 0) / 2
    metadata = max(cfg.param("METADATA_MIGRATION_MIN_NET_NEW_HOURS"), metadata_raw) if rev.customer_type == "Net_New" else metadata_raw
    put("BUILD_METADATA", "Build", "Meta Data Migration to Test Environment", metadata)
    put("BUILD_MASTER_DATA", "Build", "Master / Business Data Upload to Test Environment", metadata)

    if inp.project_type.startswith("CIP"):
        kickoff = cfg.param("KICKOFF_CIP_HOURS")
    elif inp.project_type.startswith("EPP"):
        kickoff = cfg.param("KICKOFF_EPP_HOURS")
    else:
        kickoff = cfg.param("KICKOFF_SMALL_HOURS")
    project_type_item = cfg.item_by_label("CIP Project Type", inp.project_type)
    adw = float(project_type_item.value_number or 0) if project_type_item else 0
    put("PLAN_KICKOFF", "Plan", "Project Kickoff Meeting", kickoff, allow_nonbillable=True)
    put("PLAN_ADW", "Plan", "Architecture Design Workshop (ADW) & Architecture Design Documentation (ADD)", adw, allow_nonbillable=True)
    put("PLAN_TENANT", "Plan", "Provision Customer Tenant", 0, allow_nonbillable=True)
    put("PLAN_EPP_INSTALL", "Plan", "Enterprise Printing Platform Installation", cfg.param("EPP_ON_PREM_INSTALL_HOURS") if inp.epp_install == "On Prem" else 0, allow_nonbillable=True)
    bridge_sites = max(0, int(inp.label_sites or 0) - 1)
    put("PLAN_EPP_BRIDGE", "Plan", "EPP Print Bridge Installation", cfg.param("EPP_PRINT_BRIDGE_ADDITIONAL_SITE_HOURS") * bridge_sites if inp.epp_install != "No" else 0, allow_nonbillable=True)
    put("PLAN_GATEWAY", "Plan", "Gateway Installation", cfg.param("GATEWAY_INSTALL_HOURS") if inp.gateway else 0, allow_nonbillable=True)
    access = (cfg.param("ACCESS_SETUP_HOURS") if inp.consultant_access_setup else 0) + (cfg.param("ACCESS_SETUP_HOURS") if inp.onboarding else 0)
    put("PLAN_ACCESS", "Plan", "Confirm VPN & ERP Access", access, allow_nonbillable=True)
    put("PLAN_FACILITY", "Plan", "Customer Facility Review", cfg.param("FACILITY_REVIEW_HOURS") if rev.customer_type == "Net_New" else 0, allow_nonbillable=True)
    put("PLAN_PACEJET", "Plan", "PaceJet Requirements Session", cfg.param("PACEJET_REQUIREMENTS_HOURS") if inp.pacejet else 0, allow_nonbillable=True)
    put("PLAN_ORIENTATION_PREP", "Plan", "Solution Orientation Prep", (desktop_std_count + mobile_std_count) * cfg.param("ORIENTATION_PREP_PER_STANDARD_APP"), allow_nonbillable=True)
    put("PLAN_ORIENTATION", "Plan", "Solution Orientation Session", component_count * cfg.param("ORIENTATION_SESSION_PER_COMPONENT"), allow_nonbillable=True)
    put("PLAN_GAP", "Plan", "Gap Analysis", xrnd(component_count * cfg.param("GAP_ANALYSIS_PER_COMPONENT"), 0), allow_nonbillable=True)
    brd_build_keys = ["BUILD_MODULE_SETTINGS"] + build_scope_keys
    put("PLAN_BRD", "Plan", "Business Requirements Document (BRD) Creation and Review Sessions", xrnd(sum(std(k) for k in brd_build_keys) * cfg.param("BRD_FACTOR"), 0), allow_nonbillable=True)
    plan_direct = ["PLAN_KICKOFF", "PLAN_ADW", "PLAN_TENANT", "PLAN_EPP_INSTALL", "PLAN_EPP_BRIDGE", "PLAN_GATEWAY", "PLAN_ACCESS", "PLAN_FACILITY", "PLAN_PACEJET", "PLAN_ORIENTATION_PREP", "PLAN_ORIENTATION", "PLAN_GAP", "PLAN_BRD"]
    plan_standard_base = sum(std(k) for k in plan_direct)
    plan_investment_base = sum(inv(k) for k in plan_direct)
    plan_nonbillable_base = sum(nb(k) for k in plan_direct)
    put("PLAN_PREP", "Plan", "Project preparation and setup", xrnd(plan_standard_base * cfg.param("PREP_FACTOR"), 0), allow_nonbillable=True)
    put("PLAN_PM", "Plan", "Project Management", xrnd((plan_standard_base + plan_nonbillable_base) * cfg.param("IM_FACTOR"), 0), trace="Workbook PM includes Plan Hours Not Billable in the management workload.")
    pm_adj = calc_adjustments.get("PLAN_PM")
    result["PLAN_PM"].investment_hours = xrnd((plan_investment_base + plan_nonbillable_base) * cfg.param("IM_FACTOR") + float(pm_adj.adjust_hours if pm_adj else 0), 0)
    result["PLAN_PM"].task_hours = result["PLAN_PM"].investment_hours
    contingency_factor = cfg.param("SMALL_PROJECT_CONTINGENCY_FACTOR") if inp.project_type == "Small Project" else cfg.param("CONTINGENCY_FACTOR")
    put("PLAN_CONTINGENCY", "Plan", "Plan Contingency", xrnd(plan_standard_base * contingency_factor, 0))
    cont_adj = calc_adjustments.get("PLAN_CONTINGENCY")
    result["PLAN_CONTINGENCY"].investment_hours = xrnd(plan_investment_base * contingency_factor + float(cont_adj.adjust_hours if cont_adj else 0), 0)
    result["PLAN_CONTINGENCY"].task_hours = result["PLAN_CONTINGENCY"].investment_hours

    put("DESIGN_DATA_PREP", "Design", "Internal Dev Data Upload Prep Session", cfg.param("DESIGN_DEV_DATA_PREP_HOURS") if rev.customer_type == "Net_New" else 0)
    put("DESIGN_DATA_IMPORT", "Design", "Data Import Definition & Dev Data Upload Introduction", cfg.param("DESIGN_DATA_IMPORT_HOURS") if rev.customer_type == "Net_New" else 0)
    put("DESIGN_VALIDATE_DATA", "Design", "Validate Dev Data for Upload", cfg.param("DESIGN_VALIDATE_DEV_DATA_HOURS") if rev.customer_type == "Net_New" else 0)
    put("DESIGN_CLIENT_UPLOAD", "Design", "Client Data Upload & Validation", cfg.param("DESIGN_CLIENT_DATA_UPLOAD_HOURS") if rev.customer_type == "Net_New" else 0)
    initial_script_scope = sum(std(k) for k in ["BUILD_DESKTOP_MOD", "BUILD_DESKTOP_CUSTOM", "BUILD_MOBILE_MOD", "BUILD_MOBILE_CUSTOM", "BUILD_REPORTING", "BUILD_LABELS", "BUILD_CUSTOM_BOOMI", "BUILD_REST_SERVICE", "BUILD_REST_APP_INTEGRATION"])
    put("DESIGN_INITIAL_SCRIPTS", "Design", "Generate Initial Test Scripts from BRD", xrnd(initial_script_scope * cfg.param("INITIAL_TEST_SCRIPT_FACTOR"), 0))
    put("DESIGN_APPROVE_SCRIPTS", "Design", "Approve Customer Test Scripts", xrnd(demo_component_count * cfg.param("APPROVE_TEST_SCRIPT_FACTOR"), 0))
    put("DESIGN_CI_SCRIPTS", "Design", "CI to Write Test Scripts (opt-in)", xrnd(build_scope_investment * cfg.param("CI_WRITE_TEST_SCRIPT_FACTOR"), 0) if inp.write_test_scripts else 0)
    put("DESIGN_INTERNAL_REVIEW", "Design", "Internal Solution Design Review", cfg.param("INTERNAL_DESIGN_REVIEW_HOURS") if rev.customer_type == "Net_New" else 0)
    put("DESIGN_SOLUTION", "Design", "Solution Design", xrnd(build_scope_investment * cfg.param("SOLUTION_DESIGN_FACTOR"), 0))
    design_direct = ["DESIGN_DATA_PREP", "DESIGN_DATA_IMPORT", "DESIGN_VALIDATE_DATA", "DESIGN_CLIENT_UPLOAD", "DESIGN_INITIAL_SCRIPTS", "DESIGN_APPROVE_SCRIPTS", "DESIGN_CI_SCRIPTS", "DESIGN_INTERNAL_REVIEW", "DESIGN_SOLUTION"]

    end_user_training_count = desktop_std_count + desktop_custom_count + mobile_std_count + mobile_custom_count + integration_count + report_count
    put("TEST_END_USER_TRAINING", "Test", "CI Led End User Training (opt-in)", end_user_training_count * cfg.param("END_USER_TRAINING_HOURS_PER_COMPONENT") if inp.end_user_training else 0)
    put("TEST_END_USER_DOC", "Test", "Develop End User Documentation (opt-in)", component_count * cfg.param("END_USER_DOC_HOURS_PER_COMPONENT") if inp.end_user_documentation else 0)
    put("TEST_KEY_USER_TRAINING", "Test", "Key User Application Training", component_count * cfg.param("KEY_USER_TRAINING_HOURS_PER_COMPONENT"))
    put("TEST_UAT_PREP", "Test", "UAT Prep Session", 0 if inp.project_type == "Small Project" else cfg.param("UAT_PREP_HOURS"))
    uat_mult = cfg.number_by_label("CIP UAT Site Multiplier", str(max(1, min(3, inp.uat_sites))))
    uat_once = xrnd(solution_testing_total * uat_mult, 0) if inp.testing_cycles > 0 else 0
    put("TEST_UAT_1", "Test", "User Acceptance Testing (UAT) & Issue Remediation", uat_once)
    put("TEST_UAT_2", "Test", "User Acceptance Testing (UAT) & Issue Remediation 2", uat_once if inp.testing_cycles > 1 else 0)
    put("TEST_UAT_3", "Test", "User Acceptance Testing (UAT) & Issue Remediation 3", uat_once if inp.testing_cycles > 2 else 0)
    put("TEST_LIMITED_LOAD", "Test", "Limited Load Test", cfg.param("LIMITED_LOAD_TEST_INSTALL_BASE_HOURS") if rev.customer_type == "Install_Base" else 0)
    put("TEST_READINESS", "Test", "Go-Live Readiness Assessment", cfg.param("GO_LIVE_READINESS_INSTALL_BASE_HOURS") if rev.customer_type == "Install_Base" else cfg.param("GO_LIVE_READINESS_NET_NEW_HOURS"))
    put("TEST_PROD_VALIDATION", "Test", "Go-Live Preparation and Production Validation", cfg.param("GO_LIVE_PREP_INSTALL_BASE_HOURS") if rev.customer_type == "Install_Base" else cfg.param("GO_LIVE_PREP_NET_NEW_HOURS"))
    test_direct = ["TEST_END_USER_TRAINING", "TEST_END_USER_DOC", "TEST_KEY_USER_TRAINING", "TEST_UAT_PREP", "TEST_UAT_1", "TEST_UAT_2", "TEST_UAT_3", "TEST_LIMITED_LOAD", "TEST_READINESS", "TEST_PROD_VALIDATION"]

    put("GOLIVE_PREP", "Go Live", "Go-Live Prep Meeting", cfg.param("GO_LIVE_MEETING_INSTALL_BASE_HOURS") if rev.customer_type == "Install_Base" else cfg.param("GO_LIVE_MEETING_OTHER_HOURS"))
    go_meta = cfg.json_item(cfg.item_by_label("CIP Go Live", inp.go_live_type))
    sites = max(0, int(inp.go_live_sites or 0))
    support = float(go_meta.get("base", 0)) + max(0, sites - 1) * float(go_meta.get("additional", 0)) if inp.go_live_type != "None" and sites > 0 else 0.0
    put("GOLIVE_SUPPORT", "Go Live", "Go-Live Support", support)
    go_direct = ["GOLIVE_PREP", "GOLIVE_SUPPORT"]
    build_direct = ["BUILD_SSO", "BUILD_MOBILE_DEV_TRAINING", "BUILD_CIP_DESKTOP_DEV_TRAINING", "BUILD_MODULE_SETTINGS", *build_scope_keys, "BUILD_PRINTER_DEVICE", "BUILD_DASHBOARD", "BUILD_UNIT_TESTING", "BUILD_ADMIN_TRAINING", "BUILD_PACEJET_VALIDATION", "BUILD_DEMOS", "BUILD_REMEDIATION", "BUILD_WORKSHOP", "BUILD_METADATA", "BUILD_MASTER_DATA"]

    def phase_overhead(phase: str, prefix: str, direct_keys: Iterable[str]):
        direct_keys = list(direct_keys)
        standard_base = sum(std(k) for k in direct_keys)
        investment_base = sum(inv(k) for k in direct_keys)
        pm_key, cont_key = f"{prefix}_PM", f"{prefix}_CONTINGENCY"
        put(pm_key, phase, "Project Management", xrnd(standard_base * cfg.param("IM_FACTOR"), 0))
        pm_adj2 = calc_adjustments.get(pm_key)
        result[pm_key].investment_hours = xrnd(investment_base * cfg.param("IM_FACTOR") + float(pm_adj2.adjust_hours if pm_adj2 else 0), 0)
        result[pm_key].task_hours = result[pm_key].investment_hours
        put(cont_key, phase, f"{phase} Contingency", xrnd(standard_base * contingency_factor, 0))
        c_adj = calc_adjustments.get(cont_key)
        result[cont_key].investment_hours = xrnd(investment_base * contingency_factor + float(c_adj.adjust_hours if c_adj else 0), 0)
        result[cont_key].task_hours = result[cont_key].investment_hours
        return [pm_key, cont_key] + direct_keys

    design_keys = phase_overhead("Design", "DESIGN", design_direct)
    build_keys = phase_overhead("Build", "BUILD", build_direct)
    test_keys = phase_overhead("Test", "TEST", test_direct)
    go_keys = phase_overhead("Go Live", "GOLIVE", go_direct)
    plan_keys = ["PLAN_PM", "PLAN_CONTINGENCY", "PLAN_PREP"] + plan_direct
    phase_key_map = {"Plan": plan_keys, "Design": design_keys, "Build": build_keys, "Test": test_keys, "Go Live": go_keys}
    phase_totals = {phase: {
        "standard": sum(std(k) for k in keys), "investment": sum(inv(k) for k in keys),
        "non_billable": sum(nb(k) for k in keys), "task": sum(result[k].task_hours for k in keys),
    } for phase, keys in phase_key_map.items()}
    investment_hours = sum(v["investment"] for v in phase_totals.values())
    non_billable_hours = sum(v["non_billable"] for v in phase_totals.values())
    total_internal_hours = investment_hours + non_billable_hours
    fees = investment_hours * float(rev.billing_rate)
    low_hours = xrnd(investment_hours * (1 - inp.low_factor), 0)
    high_hours = xrnd(investment_hours * (1 + inp.high_factor), 0)
    duration = xrnd((investment_hours / cfg.param("DURATION_HOURS_PER_MONTH")) * cfg.param("DURATION_FACTOR"), 2) if investment_hours else 0.0
    summary = {
        "hours": investment_hours, "investment_hours": investment_hours, "non_billable_hours": non_billable_hours,
        "total_internal_hours": total_internal_hours, "fees": fees, "low_hours": low_hours, "high_hours": high_hours,
        "low_fees": low_hours * float(rev.billing_rate), "high_fees": high_hours * float(rev.billing_rate),
        "duration_months": duration, "low_factor": inp.low_factor, "high_factor": inp.high_factor,
        "phase_totals": phase_totals, "component_count": component_count, "solution_testing_hours": solution_testing_total,
    }
    ordered = []
    for phase in ["Plan", "Design", "Build", "Test", "Go Live"]:
        ordered.extend(result[k] for k in phase_key_map[phase])
    return ordered, summary, details, detail_summary


def recalculate_and_store(db: Session, rev: EstimateRevision):
    lines, summary, details, detail_summary = calculation(db, rev)
    rev.calculated_hours = summary["investment_hours"]
    rev.calculated_fees = summary["fees"]
    rev.low_hours = summary["low_hours"]
    rev.high_hours = summary["high_hours"]
    rev.duration_months = summary["duration_months"]
    return lines, summary, details, detail_summary

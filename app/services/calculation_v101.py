from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session

from ..models import EstimateRevision, CalculationAdjustment
from .calculation import (
    CalcLine,
    Config,
    calculation as legacy_calculation,
    detail_calculation,
    xrnd as workbook_round,
)

ENGINE_VERSION = "1.0.1"
LOCKED_STATUSES = {"APPROVED", "FINAL", "SUPERSEDED"}


def q2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money(value: float) -> float:
    return q2(value)


def calculation(db: Session, rev: EstimateRevision, adjustment_overrides: dict[str, float] | None = None):
    # Historical locked revisions retain their original 1.0.0 calculation behavior.
    if rev.status in LOCKED_STATUSES and rev.engine_version != ENGINE_VERSION:
        return legacy_calculation(db, rev)

    cfg = Config(db, rev.config_version_id)
    details, summ, unit_factor = detail_calculation(db, rev)
    adjustments = {
        a.line_key: a
        for a in db.query(CalculationAdjustment)
        .filter(CalculationAdjustment.revision_id == rev.id)
        .all()
    }
    overrides = adjustment_overrides or {}
    result: dict[str, CalcLine] = {}

    def adj(key: str):
        row = adjustments.get(key)
        value = float(row.adjust_hours if row else 0.0)
        if key in overrides:
            value = float(overrides[key])
        return value, (row.notes if row else "")

    def put(key: str, phase: str, desc: str, standard: float, trace: str = ""):
        adjust, notes = adj(key)
        standard_value = q2(standard)
        extended_value = q2(standard_value + adjust)
        result[key] = CalcLine(
            key, phase, desc, standard_value, q2(adjust), extended_value, notes, trace
        )
        return result[key]

    def ext(key: str) -> float:
        return result[key].extended_hours

    def std(key: str) -> float:
        return result[key].standard_hours

    small = rev.project_type == "Small Project"
    im = cfg.param("SMALL_PROJECT_IM_FACTOR" if small else "STANDARD_IM_FACTOR")
    prep = cfg.param("SMALL_PROJECT_PREP_FACTOR" if small else "STANDARD_PREP_FACTOR")
    contingency = cfg.param("SMALL_PROJECT_CONTINGENCY" if small else "STANDARD_CONTINGENCY")
    markup = cfg.value_by_label("Delivery Method", rev.delivery_method)
    solution = cfg.json_by_label("Solution Type", rev.project_type)
    app_count = sum(1 for a in rev.applications if a.config_type in ("Baseline", "Baseline_4", "Mod Required"))
    package_count = sum(1 for a in rev.applications if a.kind == "PACKAGE" and a.config_type != "No Config")
    mod_count = sum(1 for a in rev.applications if a.kind == "APPLICATION" and a.config_type == "Mod Required")
    custom_count = sum(1 for a in rev.custom_apps if a.description and a.complexity != "No Config")
    standard_total = app_count + package_count
    component_count = standard_total + custom_count + rev.label_count + rev.iot_count + rev.erp_integration_count
    detail_dev = lambda sec: summ.get(sec, {}).get("dev", 0)
    detail_unit = lambda sec: summ.get(sec, {}).get("unit", 0)
    detail_total = lambda sec: summ.get(sec, {}).get("total", 0)
    detail_count = lambda sec: summ.get(sec, {}).get("count", 0)

    # Build. Formula-derived workbook rounding is retained where the source model uses ROUND().
    put("BUILD_APP_DEV_TRAINING", "Build", "Application Developer Training (opt-in)" if rev.app_dev_training else "Not Included - Application Developer Training (did not opt-in)", cfg.param("APP_DEV_TRAINING_HOURS") if rev.app_dev_training else 0)
    put("BUILD_STANDARD_APPS", "Build", "Standard App - FastForm Setup, App Configure", detail_dev("Baseline Applications"))
    put("BUILD_STANDARD_PACKAGES", "Build", "Standard Packages - Setup, Data Rep, Configure", detail_dev("Baseline Packages"))
    put("BUILD_CUSTOM_APPS", "Build", "Custom Applications Development / Configure", detail_dev("Custom Applications"))
    put("BUILD_LABELS", "Build", "Labels Develop / Validate", detail_dev("Labels"))
    put("BUILD_EPP_INTEGRATION", "Build", "EPP Only Project EPP Integration", cfg.value_by_label("EPP Integration", rev.epp_integration))
    put("BUILD_IOT", "Build", "IOT Interfaces", detail_dev("IoT Service Definitions"))
    put("BUILD_ERP_INTEGRATION", "Build", "ERP Integration Development / Configure", detail_dev("ERP Service Definitions"))
    put("BUILD_DATA_REP", "Build", "Setup / Configure Data Replication Session", detail_total("Data Replication Sessions"))
    put("BUILD_UPGRADE", "Build", "Upgrade App Conversion Hours", detail_dev("Upgrade Definition"))
    uc = cfg.json_by_label("User Count", rev.user_count)
    put("BUILD_HANDHELD_SETUP", "Build", "Handheld / Desktop Client Setup", 0 if small else float(uc.get("handheld_setup_hours", 0)))
    put("BUILD_PRINTER_SETUP", "Build", "Printer Setup", 0 if rev.epp_install == "No" else float(uc.get("printer_setup_hours", 0)))
    put("BUILD_UNIT_TEST_DATA", "Build", "Setup Unit Test Data", detail_count("Data Replication Sessions"))
    build_units = sum(detail_unit(s) for s in ["Upgrade Definition", "Baseline Applications", "Baseline Packages", "Custom Applications", "Labels", "IoT Service Definitions", "ERP Service Definitions"])
    put("BUILD_UNIT_TESTING", "Build", "Unit Testing & QA", build_units)
    put("BUILD_ADMIN_TRAINING", "Build", "Admin Setup User / Roles Training", cfg.param("ADMIN_TRAINING_NET_NEW_HOURS") if rev.customer_type == "Net_New" else 0)
    put("BUILD_PACEJET_VALIDATION", "Build", "Pacejet Solution Validation", cfg.param("PACEJET_VALIDATION_HOURS") if rev.pacejet else 0)
    demo = workbook_round((standard_total + custom_count) * cfg.param("APP_DEMO_HOURS_PER_APP"))
    put("BUILD_APP_DEMOS", "Build", "Application Demonstrations", demo)
    put("BUILD_REMEDIATION", "Build", "Application Remediation Review", workbook_round(demo * cfg.param("APP_REMEDIATION_FACTOR")))
    put("BUILD_WORKSHOP", "Build", "Solution Workshop / Conference Room Pilot and Train the Trainer", workbook_round(demo * cfg.param("SOLUTION_WORKSHOP_FACTOR")))
    plan_base_package = cfg.param("BASE_APP_PACKAGE_INSTALL_HOURS") if standard_total > 0 else 0
    plan_base_package_ext = plan_base_package + adj("PLAN_BASE_PACKAGE")[0]
    promotion_base = workbook_round((sum(ext(k) for k in ["BUILD_STANDARD_APPS", "BUILD_STANDARD_PACKAGES", "BUILD_CUSTOM_APPS", "BUILD_LABELS", "BUILD_EPP_INTEGRATION", "BUILD_IOT", "BUILD_ERP_INTEGRATION", "BUILD_DATA_REP", "BUILD_UPGRADE"]) + plan_base_package_ext) * cfg.param("PROMOTION_VALIDATION_FACTOR"))
    put("BUILD_PROMOTION", "Build", "Application Promotion & Stage Environment Validation", promotion_base)

    # Design.
    approve_scripts = 0 if rev.write_test_scripts else workbook_round((mod_count + package_count + custom_count) * cfg.param("CUSTOMER_TEST_SCRIPT_FACTOR"))
    put("DESIGN_APPROVE_TEST_SCRIPTS", "Design", "Approve Customer Test Scripts", approve_scripts)
    ci_scripts = workbook_round(sum(ext(k) for k in ["BUILD_STANDARD_APPS", "BUILD_STANDARD_PACKAGES", "BUILD_CUSTOM_APPS", "BUILD_LABELS", "BUILD_EPP_INTEGRATION", "BUILD_IOT", "BUILD_ERP_INTEGRATION"]) * cfg.param("CI_TEST_SCRIPT_FACTOR")) if rev.write_test_scripts else 0
    put("DESIGN_CI_TEST_SCRIPTS", "Design", "CI to Write Test Scripts (opt-in)" if rev.write_test_scripts else "Not Included - CI to Write Test Scripts (did not opt-in)", ci_scripts)
    put("DESIGN_INTERNAL_REVIEW", "Design", "Internal Solution Design Review", cfg.param("INTERNAL_DESIGN_REVIEW_HOURS") if (mod_count + custom_count) > 0 else 0)
    sol_design = workbook_round(sum(std(k) for k in ["BUILD_STANDARD_APPS", "BUILD_STANDARD_PACKAGES", "BUILD_CUSTOM_APPS", "BUILD_LABELS", "BUILD_EPP_INTEGRATION", "BUILD_IOT", "BUILD_ERP_INTEGRATION"]) * cfg.param("SOLUTION_DESIGN_FACTOR"))
    put("DESIGN_SOLUTION", "Design", "Solution Design", sol_design)

    # Test.
    put("TEST_END_USER_DOC", "Test", "Develop End User Documentation (opt-in)" if rev.end_user_documentation else "Not Included - Develop End User Documentation (did not opt-in)", (standard_total + custom_count) * cfg.param("END_USER_DOC_HOURS_PER_APP") if rev.end_user_documentation else 0)
    put("TEST_END_USER_TRAINING", "Test", "CI Led End User Training (opt-in)" if rev.end_user_training else "Not Included - CI Led End User Training (did not opt-in)", (standard_total + custom_count) * float(uc.get("multiplier", 0)) if rev.end_user_training else 0)
    put("TEST_UAT_PREP", "Test", "User Acceptance Testing (UAT) Prep Session", 0 if small else cfg.param("UAT_PREP_STANDARD_HOURS"))
    put("TEST_UAT_DATA", "Test", "UAT Data Setup", detail_count("Data Replication Sessions"))
    uat_mult = cfg.value_by_label("UAT Site Multiplier", str(max(1, min(3, rev.uat_sites))))
    build_scope = sum(ext(k) for k in ["BUILD_STANDARD_APPS", "BUILD_STANDARD_PACKAGES", "BUILD_CUSTOM_APPS", "BUILD_LABELS", "BUILD_EPP_INTEGRATION", "BUILD_IOT", "BUILD_ERP_INTEGRATION", "BUILD_DATA_REP", "BUILD_UPGRADE"])
    uat = workbook_round(build_scope * rev.base_test_pct * uat_mult)
    put("TEST_UAT_1", "Test", "User Acceptance Testing (UAT) & Issue Remediation", uat)
    put("TEST_UAT_2", "Test", "User Acceptance Testing (UAT) & Issue Remediation 2", uat if rev.test_cycles >= 2 else 0)
    put("TEST_UAT_3", "Test", "User Acceptance Testing (UAT) & Issue Remediation 3", uat if rev.test_cycles >= 3 else 0)
    put("TEST_LOAD", "Test", "Platform Limited Load Test", float(solution.get("load_test_effort", 0)))
    count_sum = detail_count("Upgrade Definition") + detail_count("Baseline Applications") * 2 + detail_count("Baseline Packages") + detail_count("Custom Applications") + detail_count("Labels") + detail_count("IoT Service Definitions") + detail_count("ERP Service Definitions")
    put("TEST_READINESS", "Test", "Go-Live Readiness Assessment", workbook_round(count_sum * cfg.param("LOAD_TEST_FACTOR")))
    put("TEST_PROD_VALIDATION", "Test", "Go-Live Prep & Production Validation Testing", workbook_round(count_sum * cfg.param("GO_LIVE_PREP_VALIDATION_FACTOR")))

    # Go Live.
    gl_prep = workbook_round(sum(ext(k) for k in ["BUILD_STANDARD_APPS", "BUILD_CUSTOM_APPS", "BUILD_LABELS", "BUILD_IOT", "BUILD_UPGRADE"]) * cfg.param("GO_LIVE_PREP_FACTOR"))
    put("GO_LIVE_PREP", "Go Live", "Go-Live Prep Meeting", gl_prep)
    sites = max(rev.go_live_sites, 0)
    support = 0
    if rev.go_live_type == "Remote All" and sites > 0:
        support = cfg.param("GO_LIVE_REMOTE_BASE_HOURS") + max(0, sites - 1) * cfg.param("GO_LIVE_REMOTE_EXTRA_SITE_HOURS")
    elif rev.go_live_type == "On-Site All" and sites > 0:
        support = cfg.param("GO_LIVE_ONSITE_BASE_HOURS") + max(0, sites - 1) * cfg.param("GO_LIVE_ONSITE_EXTRA_SITE_HOURS")
    elif rev.go_live_type == "On-Site Primary Remote Others" and sites > 0:
        support = cfg.param("GO_LIVE_ONSITE_BASE_HOURS") + max(0, sites - 1) * cfg.param("GO_LIVE_HYBRID_EXTRA_SITE_HOURS")
    put("GO_LIVE_SUPPORT", "Go Live", "Go-Live Support", support)

    # Plan.
    kickoff = cfg.param("PROJECT_KICKOFF_NET_NEW_HOURS") if rev.customer_type == "Net_New" else (cfg.param("PROJECT_KICKOFF_SMALL_HOURS") if small else cfg.param("PROJECT_KICKOFF_STANDARD_HOURS"))
    put("PLAN_KICKOFF", "Plan", "Project Kickoff Meeting", kickoff)
    put("PLAN_ADW", "Plan", "Architecture Design Workshop (ADW) & Architecture Design Document (ADD)", float(solution.get("adw_hours", 0)))
    mep_install = 0 if rev.project_type.startswith("EPP") else float(solution.get("on_prem_hours", 0)) + (cfg.param("HA_INSTALL_INCREMENT_HOURS") if rev.high_availability else 0)
    put("PLAN_MEP_INSTALL", "Plan", "MEP Cloud Installation" if solution.get("cloud_flag") else "MEP On-Premise Installation", mep_install)
    put("PLAN_EPP_INSTALL", "Plan", "Enterprise Printing Platform Installation", cfg.param("EPP_ON_PREM_INSTALL_HOURS") if rev.epp_install == "On Prem" else 0)
    put("PLAN_PRINT_BRIDGE", "Plan", "EPP Print Bridge Installation", cfg.param("PRINT_BRIDGE_INSTALL_HOURS") * max(0, rev.label_sites - 1) if rev.epp_install != "No" else 0)
    put("PLAN_GATEWAY", "Plan", "Gateway Installation", cfg.param("GATEWAY_INSTALL_HOURS") if rev.gateway else 0)
    put("PLAN_SSO", "Plan", "SSO Setup / Configure", cfg.value_by_label("Security Method", rev.security_method) if rev.security_method != "None" else 0)
    put("PLAN_BASE_PACKAGE", "Plan", "Base Application Package Install", plan_base_package)
    put("PLAN_FACILITY", "Plan", "Customer Facility Review", cfg.param("CUSTOMER_FACILITY_REVIEW_HOURS") if rev.customer_type == "Net_New" else 0)
    put("PLAN_ACCESS", "Plan", "Confirm VPN & ERP Accesss", (cfg.param("ACCESS_CONFIRMATION_HOURS") if rev.consultant_access_setup else 0) + (cfg.param("ACCESS_CONFIRMATION_HOURS") if rev.onboarding else 0))
    put("PLAN_PACEJET", "Plan", "Pacejet Requirements Session", cfg.param("PACEJET_REQUIREMENTS_HOURS") if rev.pacejet else 0)
    put("PLAN_ORIENTATION_PREP", "Plan", "Solution Orientation Prep", standard_total)
    count_basis = sum(detail_count(s) for s in ["Baseline Applications", "Baseline Packages", "Custom Applications", "Labels", "IoT Service Definitions", "ERP Service Definitions"])
    orient = (workbook_round(count_basis * cfg.param("SOLUTION_ORIENTATION_FACTOR_1")) + workbook_round(count_basis * cfg.param("SOLUTION_ORIENTATION_FACTOR_2"))) if standard_total > 0 else 0
    put("PLAN_ORIENTATION", "Plan", "Solution Orientation Session", orient)
    put("PLAN_GAP", "Plan", "Gap Analysis", workbook_round(count_basis * cfg.param("GAP_ANALYSIS_FACTOR")) if component_count > 0 else 0)
    brd = workbook_round(sum(std(k) for k in ["BUILD_STANDARD_APPS", "BUILD_STANDARD_PACKAGES", "BUILD_CUSTOM_APPS", "BUILD_LABELS", "BUILD_EPP_INTEGRATION", "BUILD_IOT", "BUILD_ERP_INTEGRATION"]) * cfg.param("BRD_FACTOR")) if component_count > 0 else 0
    put("PLAN_BRD", "Plan", "Business Requirement Document (BRD) Creation & Review Sessions", brd)

    phase_children = {
        "Plan": ["PLAN_KICKOFF", "PLAN_ADW", "PLAN_MEP_INSTALL", "PLAN_EPP_INSTALL", "PLAN_PRINT_BRIDGE", "PLAN_GATEWAY", "PLAN_SSO", "PLAN_BASE_PACKAGE", "PLAN_FACILITY", "PLAN_ACCESS", "PLAN_PACEJET", "PLAN_ORIENTATION_PREP", "PLAN_ORIENTATION", "PLAN_GAP", "PLAN_BRD"],
        "Design": ["DESIGN_APPROVE_TEST_SCRIPTS", "DESIGN_CI_TEST_SCRIPTS", "DESIGN_INTERNAL_REVIEW", "DESIGN_SOLUTION"],
        "Build": ["BUILD_APP_DEV_TRAINING", "BUILD_STANDARD_APPS", "BUILD_STANDARD_PACKAGES", "BUILD_CUSTOM_APPS", "BUILD_LABELS", "BUILD_EPP_INTEGRATION", "BUILD_IOT", "BUILD_ERP_INTEGRATION", "BUILD_DATA_REP", "BUILD_UPGRADE", "BUILD_HANDHELD_SETUP", "BUILD_PRINTER_SETUP", "BUILD_UNIT_TEST_DATA", "BUILD_UNIT_TESTING", "BUILD_ADMIN_TRAINING", "BUILD_PACEJET_VALIDATION", "BUILD_APP_DEMOS", "BUILD_REMEDIATION", "BUILD_WORKSHOP", "BUILD_PROMOTION"],
        "Test": ["TEST_END_USER_DOC", "TEST_END_USER_TRAINING", "TEST_UAT_PREP", "TEST_UAT_DATA", "TEST_UAT_1", "TEST_UAT_2", "TEST_UAT_3", "TEST_LOAD", "TEST_READINESS", "TEST_PROD_VALIDATION"],
        "Go Live": ["GO_LIVE_PREP", "GO_LIVE_SUPPORT"],
    }

    for phase, children in phase_children.items():
        pkey = phase.upper().replace(" ", "_")
        child_std = sum(std(k) for k in children)
        child_ext = sum(ext(k) for k in children)

        pm_adjust, pm_notes = adj(f"{pkey}_PM")
        pm_std = workbook_round(child_std * im)
        pm_extended = q2(workbook_round(child_ext * im) + pm_adjust)
        result[f"{pkey}_PM"] = CalcLine(f"{pkey}_PM", phase, f"{phase} Project Management", q2(pm_std), q2(pm_adjust), pm_extended, pm_notes, f"ROUND(child hours × {im:.1%}) + adjustment")

        cont_adjust, cont_notes = adj(f"{pkey}_CONTINGENCY")
        cont_std = workbook_round(child_std * contingency + child_std * markup)
        cont_extended = q2(workbook_round(child_ext * contingency + child_ext * markup) + cont_adjust)
        result[f"{pkey}_CONTINGENCY"] = CalcLine(f"{pkey}_CONTINGENCY", phase, f"{phase} Contingency", q2(cont_std), q2(cont_adjust), cont_extended, cont_notes, f"ROUND(child hours × contingency/markup) + adjustment")

        if phase == "Plan":
            prep_adjust, prep_notes = adj("PLAN_PREP")
            prep_std = workbook_round(child_std * prep)
            prep_extended = q2(workbook_round(child_ext * prep) + prep_adjust)
            result["PLAN_PREP"] = CalcLine("PLAN_PREP", "Plan", "Project preparation and setup", q2(prep_std), q2(prep_adjust), prep_extended, prep_notes, f"ROUND(child hours × {prep:.1%}) + adjustment")

    phase_defs = [
        ("Plan", ["PLAN_PM", "PLAN_CONTINGENCY", "PLAN_PREP"] + phase_children["Plan"]),
        ("Design", ["DESIGN_PM", "DESIGN_CONTINGENCY"] + phase_children["Design"]),
        ("Build", ["BUILD_PM", "BUILD_CONTINGENCY"] + phase_children["Build"]),
        ("Test", ["TEST_PM", "TEST_CONTINGENCY"] + phase_children["Test"]),
        ("Go Live", ["GO_LIVE_PM", "GO_LIVE_CONTINGENCY"] + phase_children["Go Live"]),
    ]
    totals = {}
    ordered = []
    for phase, keys in phase_defs:
        rows = [result[k] for k in keys]
        totals[phase] = {
            "standard": q2(sum(x.standard_hours for x in rows)),
            "extended": q2(sum(x.extended_hours for x in rows)),
        }
        ordered.extend(rows)

    total = q2(sum(t["extended"] for t in totals.values()))
    billing_rate = float(rev.billing_rate or 0)
    fees = money(total * billing_rate)
    low_factor = cfg.param("LOW_RANGE_FACTOR")
    high_factor = cfg.param("HIGH_RANGE_FACTOR")
    low = q2(total * (1 - low_factor))
    high = q2(total * (1 + high_factor))
    duration = q2((total / cfg.param("ESTIMATE_DURATION_HOURS_PER_MONTH")) * cfg.param("ESTIMATE_DURATION_UTILIZATION")) if total else 0.0
    summary = {
        "hours": total,
        "fees": fees,
        "low_hours": low,
        "low_fees": money(low * billing_rate),
        "high_hours": high,
        "high_fees": money(high * billing_rate),
        "duration_months": duration,
        "unit_test_factor": unit_factor,
        "phase_totals": totals,
        "markup": markup,
        "low_factor": low_factor,
        "high_factor": high_factor,
    }
    return ordered, summary, details, summ


def recalculate_and_store(db: Session, rev: EstimateRevision):
    if rev.status in LOCKED_STATUSES and rev.engine_version != ENGINE_VERSION:
        return legacy_calculation(db, rev)
    lines, summary, details, summ = calculation(db, rev)
    rev.calculated_hours = summary["hours"]
    rev.calculated_fees = summary["fees"]
    rev.low_hours = summary["low_hours"]
    rev.high_hours = summary["high_hours"]
    rev.duration_months = summary["duration_months"]
    rev.engine_version = ENGINE_VERSION
    db.flush()
    return lines, summary, details, summ

from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from .cip_models import CIPRevisionInput
from .models import ConfigItem, EstimateRevision


MEP_RULES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "BUILD_APP_DEV_TRAINING": ("Uses the configured Application Developer Training hours when the estimate opts in; otherwise 0.", ("APP_DEV_TRAINING_HOURS",), "Application Developer Training selection"),
    "BUILD_STANDARD_APPS": ("Sum of development hours from selected Baseline/Modified applications in Estimate Detail.", (), "Application selections and configuration effort"),
    "BUILD_STANDARD_PACKAGES": ("Sum of development hours from selected baseline packages in Estimate Detail.", (), "Package selections and configuration effort"),
    "BUILD_CUSTOM_APPS": ("Sum of development hours from configured Custom Applications in Estimate Detail.", (), "Custom Application descriptions and complexity"),
    "BUILD_LABELS": ("Sum of label development hours from Estimate Detail.", ("LABEL_BASE_HOURS",), "Label count and label detail"),
    "BUILD_EPP_INTEGRATION": ("Uses the Calculation Data value for the selected EPP Integration option.", (), "EPP Integration selection"),
    "BUILD_IOT": ("Sum of development hours for configured conveyor/scale service definitions.", ("IOT_SERVICE_DEF_HOURS",), "Conveyor/scale service definition count"),
    "BUILD_ERP_INTEGRATION": ("Sum of ERP integration development hours from Estimate Detail.", ("ERP_SERVICE_DEF_HOURS",), "ERP integration count"),
    "BUILD_DATA_REP": ("Sum of Data Replication development plus unit-testing effort from Estimate Detail.", ("DATA_REP_SESSION_HOURS",), "Data Replication session count"),
    "BUILD_UPGRADE": ("Uses the Upgrade Estimate Detail development subtotal, including selected upgrade type/count and any approved detail adjustment.", ("UPGRADE_FIXED_DEV_HOURS", "UPGRADE_ANDROID_FACTOR"), "Upgrade type, application count and Android-change selection"),
    "BUILD_HANDHELD_SETUP": ("Uses the handheld/desktop setup hours stored with the selected User Count; Small Projects use 0.", (), "User Count and Project Type"),
    "BUILD_PRINTER_SETUP": ("Uses printer setup hours stored with the selected User Count when EPP is installed; otherwise 0.", (), "User Count and EPP installation selection"),
    "BUILD_UNIT_TEST_DATA": ("One Standard Hour per configured Data Replication session represented in Estimate Detail.", (), "Data Replication session count"),
    "BUILD_UNIT_TESTING": ("Sum of the unit-testing hours calculated across Upgrade, application, package, custom app, label, IoT and ERP integration detail rows.", ("UNIT_TEST_FACTOR",), "Estimate Detail development effort and Unit Test Factor"),
    "BUILD_ADMIN_TRAINING": ("Uses configured Admin Training hours for Net New customers; Install Base uses 0.", ("ADMIN_TRAINING_NET_NEW_HOURS",), "Customer Type"),
    "BUILD_PACEJET_VALIDATION": ("Uses configured PaceJet validation hours when PaceJet is selected; otherwise 0.", ("PACEJET_VALIDATION_HOURS",), "PaceJet selection"),
    "BUILD_APP_DEMOS": ("Workbook-rounded selected standard/package/custom component count multiplied by demo hours per application.", ("APP_DEMO_HOURS_PER_APP",), "Selected standard, package and custom application count"),
    "BUILD_REMEDIATION": ("Workbook-rounded Application Demonstration Standard Hours multiplied by the remediation factor.", ("APP_REMEDIATION_FACTOR",), "Application Demonstration hours"),
    "BUILD_WORKSHOP": ("Workbook-rounded Application Demonstration Standard Hours multiplied by the Solution Workshop factor.", ("SOLUTION_WORKSHOP_FACTOR",), "Application Demonstration hours"),
    "BUILD_PROMOTION": ("Workbook-rounded adjusted implementation/build scope plus Base Application Package install effort multiplied by the promotion-validation factor.", ("PROMOTION_VALIDATION_FACTOR",), "Selected implementation/build scope"),
    "DESIGN_APPROVE_TEST_SCRIPTS": ("When CI is not writing scripts, workbook-rounded modified/package/custom component count multiplied by the customer test-script factor; otherwise 0.", ("CUSTOMER_TEST_SCRIPT_FACTOR",), "Write Test Scripts selection and component count"),
    "DESIGN_CI_TEST_SCRIPTS": ("When CI writes test scripts, workbook-rounded adjusted build scope multiplied by the CI test-script factor; otherwise 0.", ("CI_TEST_SCRIPT_FACTOR",), "Write Test Scripts selection and adjusted build scope"),
    "DESIGN_INTERNAL_REVIEW": ("Uses configured Internal Design Review hours when modified or custom applications exist; otherwise 0.", ("INTERNAL_DESIGN_REVIEW_HOURS",), "Modified/custom application count"),
    "DESIGN_SOLUTION": ("Workbook-rounded sum of standard build effort multiplied by the Solution Design factor.", ("SOLUTION_DESIGN_FACTOR",), "Standard build scope"),
    "TEST_END_USER_DOC": ("Selected application/package/custom count multiplied by configured documentation hours per application when opted in; otherwise 0.", ("END_USER_DOC_HOURS_PER_APP",), "End User Documentation selection and component count"),
    "TEST_UAT_PREP": ("Uses configured Standard UAT Prep hours unless Project Type is Small Project, which uses 0.", ("UAT_PREP_STANDARD_HOURS",), "Project Type"),
    "TEST_UAT_DATA": ("One Standard Hour per Data Replication session represented in Estimate Detail.", (), "Data Replication session count"),
    "TEST_UAT_1": ("Workbook-rounded adjusted build scope multiplied by Base Test % and the configured UAT Site Multiplier.", (), "Adjusted build scope, Base Test %, UAT sites"),
    "TEST_UAT_2": ("Same calculated UAT-cycle hours as UAT 1 when Testing Cycles is at least 2; otherwise 0.", (), "Testing Cycles and UAT 1 basis"),
    "TEST_UAT_3": ("Same calculated UAT-cycle hours as UAT 1 when Testing Cycles is 3; otherwise 0.", (), "Testing Cycles and UAT 1 basis"),
    "TEST_READINESS": ("Workbook-rounded weighted solution-component count multiplied by the Limited Load Test factor.", ("LOAD_TEST_FACTOR",), "Selected solution-component count"),
    "TEST_PROD_VALIDATION": ("Workbook-rounded weighted solution-component count multiplied by the Go-Live Prep/Validation factor.", ("GO_LIVE_PREP_VALIDATION_FACTOR",), "Selected solution-component count"),
    "GO_LIVE_PREP": ("Workbook-rounded adjusted implementation scope multiplied by the Go-Live Prep factor.", ("GO_LIVE_PREP_FACTOR",), "Adjusted build scope"),
    "GO_LIVE_SUPPORT": ("Uses the selected Go-Live support model's base hours plus its configured additional-site hours.", ("GO_LIVE_REMOTE_BASE_HOURS", "GO_LIVE_REMOTE_EXTRA_SITE_HOURS", "GO_LIVE_ONSITE_BASE_HOURS", "GO_LIVE_ONSITE_EXTRA_SITE_HOURS", "GO_LIVE_HYBRID_EXTRA_SITE_HOURS"), "Go-Live Type and number of Go-Live sites"),
    "PLAN_ADW": ("Uses the Architecture Design Workshop hours stored in the selected Solution Type metadata.", (), "Project/Solution Type"),
    "PLAN_EPP_INSTALL": ("Uses configured EPP On-Prem installation hours only when EPP installation is On Prem.", ("EPP_ON_PREM_INSTALL_HOURS",), "EPP installation selection"),
    "PLAN_PRINT_BRIDGE": ("Configured Print Bridge hours multiplied by additional label-printing sites after the first site when EPP is installed.", ("PRINT_BRIDGE_INSTALL_HOURS",), "EPP installation and label-printing sites"),
    "PLAN_GATEWAY": ("Uses configured Gateway Installation hours when Gateway is selected; otherwise 0.", ("GATEWAY_INSTALL_HOURS",), "Gateway selection"),
    "PLAN_SSO": ("Uses the Calculation Data value for the selected Security Method when security is not None.", (), "Security Method"),
    "PLAN_BASE_PACKAGE": ("Uses configured Base Application Package Install hours when at least one standard application/package is selected; otherwise 0.", ("BASE_APP_PACKAGE_INSTALL_HOURS",), "Selected standard application/package count"),
    "PLAN_FACILITY": ("Uses configured Customer Facility Review hours for Net New customers; otherwise 0.", ("CUSTOMER_FACILITY_REVIEW_HOURS",), "Customer Type"),
    "PLAN_ACCESS": ("Adds configured Access Confirmation hours once for Consultant Access Setup and once for Onboarding when selected.", ("ACCESS_CONFIRMATION_HOURS",), "Consultant Access Setup and Onboarding selections"),
    "PLAN_PACEJET": ("Uses configured PaceJet Requirements hours when PaceJet is selected; otherwise 0.", ("PACEJET_REQUIREMENTS_HOURS",), "PaceJet selection"),
    "PLAN_ORIENTATION_PREP": ("One Standard Hour per selected standard application/package component.", (), "Selected standard component count"),
    "PLAN_ORIENTATION": ("Workbook-rounded component count multiplied by both configured Solution Orientation factors and added together.", ("SOLUTION_ORIENTATION_FACTOR_1", "SOLUTION_ORIENTATION_FACTOR_2"), "Selected solution-component count"),
    "PLAN_GAP": ("Workbook-rounded component count multiplied by the Gap Analysis factor when solution components are in scope.", ("GAP_ANALYSIS_FACTOR",), "Selected solution-component count"),
    "PLAN_BRD": ("Workbook-rounded standard build scope multiplied by the BRD factor when solution components are in scope.", ("BRD_FACTOR",), "Standard build scope"),
}

CIP_RULES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "BUILD_SSO": ("Uses configured SSO Setup hours when Security Method is not None; otherwise 0.", ("SSO_SETUP_HOURS",), "Security Method"),
    "BUILD_MODULE_SETTINGS": ("Uses the configured Module Settings hours for Install Base or Net New customer type.", ("MODULE_SETTINGS_INSTALL_BASE_HOURS", "MODULE_SETTINGS_NET_NEW_HOURS"), "Customer Type"),
    "BUILD_UNIT_TESTING": ("Sum of unit-testing effort generated by the selected CIP Estimate Detail components and testing modifiers.", (), "CIP Estimate Detail scope and test modifiers"),
    "BUILD_ADMIN_TRAINING": ("Uses configured Admin Training hours for Net New customers; otherwise 0.", ("ADMIN_TRAINING_HOURS",), "Customer Type"),
    "BUILD_DEMOS": ("Workbook-rounded demo component count multiplied by demo hours per application.", ("APP_DEMO_HOURS_PER_APP",), "Selected Desktop/Mobile/custom/report components"),
    "BUILD_REMEDIATION": ("Workbook-rounded Application Demonstration hours multiplied by the remediation factor.", ("APP_REMEDIATION_FACTOR",), "Application Demonstration hours"),
    "BUILD_WORKSHOP": ("Workbook-rounded Application Demonstration hours multiplied by the Solution Workshop factor.", ("SOLUTION_WORKSHOP_FACTOR",), "Application Demonstration hours"),
    "BUILD_METADATA": ("Adjusted build-scope investment multiplied by the Metadata Migration factor, divided by two, with the Net New minimum applied where required.", ("METADATA_MIGRATION_FACTOR", "METADATA_MIGRATION_MIN_NET_NEW_HOURS"), "Build scope and Customer Type"),
    "BUILD_MASTER_DATA": ("Uses the same calculated basis as Metadata Migration for the test-environment master/business data upload.", ("METADATA_MIGRATION_FACTOR", "METADATA_MIGRATION_MIN_NET_NEW_HOURS"), "Build scope and Customer Type"),
    "PLAN_EPP_INSTALL": ("Uses configured EPP On-Prem installation hours when EPP Install is On Prem; otherwise 0.", ("EPP_ON_PREM_INSTALL_HOURS",), "EPP Install"),
    "PLAN_EPP_BRIDGE": ("Configured additional-site Print Bridge hours multiplied by label-printing sites after the first site when EPP is installed.", ("EPP_PRINT_BRIDGE_ADDITIONAL_SITE_HOURS",), "EPP Install and label-printing sites"),
    "PLAN_GATEWAY": ("Uses configured Gateway Installation hours when Gateway is selected; otherwise 0.", ("GATEWAY_INSTALL_HOURS",), "Gateway selection"),
    "PLAN_ACCESS": ("Adds configured Access Setup hours for each selected access/onboarding requirement.", ("ACCESS_SETUP_HOURS",), "Consultant Access Setup and Onboarding"),
    "PLAN_FACILITY": ("Uses configured Facility Review hours for Net New customers; otherwise 0.", ("FACILITY_REVIEW_HOURS",), "Customer Type"),
    "PLAN_PACEJET": ("Uses configured PaceJet Requirements hours when selected; otherwise 0.", ("PACEJET_REQUIREMENTS_HOURS",), "PaceJet selection"),
    "PLAN_ORIENTATION_PREP": ("Selected standard Desktop/Mobile application count multiplied by configured orientation-prep hours per standard app.", ("ORIENTATION_PREP_PER_STANDARD_APP",), "Selected standard Desktop/Mobile applications"),
    "PLAN_ORIENTATION": ("Selected solution-component count multiplied by configured orientation-session hours per component.", ("ORIENTATION_SESSION_PER_COMPONENT",), "Selected solution-component count"),
    "PLAN_GAP": ("Workbook-rounded solution-component count multiplied by the Gap Analysis hours per component.", ("GAP_ANALYSIS_PER_COMPONENT",), "Selected solution-component count"),
    "PLAN_BRD": ("Workbook-rounded BRD build-scope Standard Hours multiplied by the BRD factor.", ("BRD_FACTOR",), "BRD build scope"),
    "DESIGN_CI_SCRIPTS": ("When CI writes test scripts, workbook-rounded adjusted build-scope investment multiplied by the CI Write Test Script factor; otherwise 0.", ("CI_WRITE_TEST_SCRIPT_FACTOR",), "Write Test Scripts selection and build scope"),
    "DESIGN_INTERNAL_REVIEW": ("Uses configured Internal Design Review hours for Net New; otherwise 0.", ("INTERNAL_DESIGN_REVIEW_HOURS",), "Customer Type"),
    "DESIGN_SOLUTION": ("Workbook-rounded adjusted build-scope investment multiplied by the Solution Design factor.", ("SOLUTION_DESIGN_FACTOR",), "Adjusted build scope"),
    "TEST_UAT_PREP": ("Uses configured UAT Prep hours unless Project Type is Small Project; Small Project uses 0.", ("UAT_PREP_HOURS",), "Project Type"),
}


def _config_text(items: Iterable[ConfigItem], keys: Iterable[str]) -> str:
    wanted = list(keys)
    if not wanted:
        return "Derived from selected estimate/detail scope; no single standalone Calculation Data value controls this line."
    by_key = {item.key: item for item in items}
    values: list[str] = []
    for key in wanted:
        item = by_key.get(key)
        if not item:
            values.append(f"{key}=not present in pinned configuration")
            continue
        value = item.value_number if item.value_number is not None else item.value_text
        unit = f" {item.unit}" if item.unit else ""
        values.append(f"{item.label} [{item.key}] = {value}{unit}")
    return "; ".join(values)


def _phase_overhead(line_key: str, project_type: str, product: str) -> tuple[str, tuple[str, ...], str] | None:
    if line_key.endswith("_PM"):
        if product == "MEP":
            key = "SMALL_PROJECT_IM_FACTOR" if project_type == "Small Project" else "STANDARD_IM_FACTOR"
        else:
            key = "IM_FACTOR"
        return ("Project Management is calculated from the applicable phase child-hour basis multiplied by the configured implementation-management factor. Manual Standard Adjust follows the engine's controlled adjustment rule.", (key,), "Applicable phase child hours")
    if line_key.endswith("_CONTINGENCY"):
        if product == "MEP":
            key = "SMALL_PROJECT_CONTINGENCY" if project_type == "Small Project" else "STANDARD_CONTINGENCY"
            return ("Contingency is calculated from phase child hours using the configured contingency factor plus the selected Delivery Method markup. Standard Adjust is shown separately.", (key,), "Phase child hours and Delivery Method")
        key = "SMALL_PROJECT_CONTINGENCY_FACTOR" if project_type == "Small Project" else "CONTINGENCY_FACTOR"
        return ("Contingency is calculated from phase child investment using the configured contingency factor. Standard Adjust is shown separately.", (key,), "Phase child investment hours")
    if line_key == "PLAN_PREP":
        key = "SMALL_PROJECT_PREP_FACTOR" if product == "MEP" and project_type == "Small Project" else ("STANDARD_PREP_FACTOR" if product == "MEP" else "PREP_FACTOR")
        return ("Project preparation is calculated from the Plan child-hour basis multiplied by the configured preparation factor.", (key,), "Plan child hours")
    return None


def enrich_mep_lines(db: Session, rev: EstimateRevision, lines):
    items = db.query(ConfigItem).filter(ConfigItem.config_version_id == rev.config_version_id).all()
    for line in lines:
        rule = MEP_RULES.get(line.key) or _phase_overhead(line.key, rev.project_type, "MEP")
        if rule:
            formula, keys, inputs = rule
        else:
            formula, keys, inputs = (
                "Standard Hours are produced by the MEP calculation engine from the selected estimate/detail scope for this rule. The displayed result is the engine output; this explanation does not recalculate it.",
                (),
                "Selected estimate and Estimate Detail scope",
            )
        prior = f" Existing engine trace: {line.trace}" if getattr(line, "trace", "") else ""
        line.trace = (
            f"Standard Hours: {line.standard_hours}. {formula} "
            f"Inputs: {inputs}. Calculation Data: {_config_text(items, keys)}. "
            f"Pinned model: Configuration {rev.config_version_id}; Engine {rev.engine_version}. "
            f"Standard Adjust ({line.adjust_hours}) is user-entered and is not part of Standard Hours.{prior}"
        )
    return lines


def enrich_cip_lines(db: Session, rev: EstimateRevision, lines):
    inp = db.get(CIPRevisionInput, rev.id)
    project_type = inp.project_type if inp else rev.project_type
    items = db.query(ConfigItem).filter(ConfigItem.config_version_id == rev.config_version_id).all()
    for line in lines:
        rule = CIP_RULES.get(line.key) or _phase_overhead(line.key, project_type, "CIP")
        if rule:
            formula, keys, inputs = rule
        else:
            formula, keys, inputs = (
                "Standard Hours are produced by the CIP calculation engine from the selected CIP Estimate Detail scope for this rule. The displayed result is the engine output; this explanation does not recalculate it.",
                (),
                "Selected CIP estimate and Estimate Detail scope",
            )
        prior = f" Existing engine trace: {line.trace}" if getattr(line, "trace", "") else ""
        line.trace = (
            f"Standard Hours: {line.standard_hours}. {formula} "
            f"Inputs: {inputs}. Calculation Data: {_config_text(items, keys)}. "
            f"Pinned model: Configuration {rev.config_version_id}; Engine {rev.engine_version}. "
            f"Standard Adjust ({line.adjust_hours}) is user-entered and is not part of Standard Hours. "
            f"Plan Hours Not Billable ({line.non_billable_hours}) affect internal Task Hours but not customer Investment Hours.{prior}"
        )
    return lines


def install_calculation_explanations(core) -> None:
    """Decorate calculation output only; numeric calculations remain source controlled."""
    original_mep = core.calculation

    def mep_with_explanations(db, rev, *args, **kwargs):
        lines, summary, details, detail_summary = original_mep(db, rev, *args, **kwargs)
        return enrich_mep_lines(db, rev, lines), summary, details, detail_summary

    core.calculation = mep_with_explanations

    from . import cip_domain, cip_routes_detail

    original_cip = cip_routes_detail.cip_calculation

    def cip_with_explanations(db, rev, *args, **kwargs):
        lines, summary, details, detail_summary = original_cip(db, rev, *args, **kwargs)
        return enrich_cip_lines(db, rev, lines), summary, details, detail_summary

    cip_routes_detail.cip_calculation = cip_with_explanations
    # Keep read-only contexts that use cip_domain aligned. Recalculation functions are
    # intentionally untouched so explanation generation can never alter stored results.
    cip_domain.cip_calculation = cip_with_explanations

# Automated Test Coverage Matrix

**Governing baseline:** Cloud Inventory Services Estimator No-Code Reconstruction Specification v0.3.25.1 / controlled reconstruction baseline `6f724b7dcce4ae3f798df2e5d0fa661c52a1a171`, superseded for CIP-1.0.2 funding semantics by [the approved clarification](INVESTMENT_FUNDING_CLARIFICATION.md).

**Executed browser evidence:** commit `40f028e822ac035d7914fecfe46c8704936f00d9`, [Browser Tests run 36921422411](https://github.com/campbellhatchard/mep-estimate-app/actions/runs/36921422411): **6 smoke + 10 release-only passed**, zero retries, PostgreSQL 18 / Chromium. Deterministic results and subsequent documentation-head checks are recorded in [verification record](PHASE1_VERIFICATION.md) and PR #66.

Coverage status is deliberately evidence-based. `Implemented` means an automated test exists. It does not mean the requirement is passing. `Passing` is used only after an executed test demonstrates the expected result. `Blocked — defect` means the test is intentionally left failing because current implementation conflicts with the governing requirement.

| Requirement | Specification section | Test ID | Layer | Criticality | Status | Expected result / current evidence |
|---|---|---|---|---|---|---|
| Active/inactive authentication | 3, 7.1 | `test_authentication_active_and_inactive` | Browser | P1 | **Passing — browser smoke** | Active succeeds; inactive denied through normal authentication. |
| Multi-role / Read Only / Tools Admin | 3 | `test_role_union_readonly_and_tools_admin_boundaries` | Browser | P0 | **Passing — browser smoke** | Union permissions; Read Only controlled mutation denied; Tools Admin cannot access Users. |
| Last active Administrator | 3.3, 12 | `test_last_active_administrator_protection_through_user_ui` | Browser | P0 | **Passing — browser release** | Server refuses removal/deactivation of final active Administrator. |
| MEP product/config/engine pin | 1.3, 6.3 | `test_mep_creation_pins_product_configuration_and_engine` | Browser | P0 | **Passing — browser smoke** | YYYYMMNNN identity, MEP product immutable, configuration and engine pinned. |
| MEP Golden matrix | 8, Appendix A | `test_mep_golden_scenario_matrix` | Golden/domain | P0 | **Passing — deterministic suite** | 12 fixed MEP scenarios. Exact expected values remain independent test-oracle data, not learned during execution. |
| CIP Golden matrix | 9, Appendix B | `test_cip_golden_scenario_matrix` | Golden/domain | P0 | **Passing — deterministic suite** | 12 fixed CIP scenarios. EPP On Prem is tested independently from optional Gateway scope. |
| MEP autosave / ERP reset / .5 adjustment | 6.3, 6.5, Section 15 | `test_mep_autosave_erp_reset_detail_adjustment_and_golden_reload` + `test_mep_save_adjustment_synchronizes_persisted_summary` | Browser + integration | P0 | **Passing — browser smoke + integration** | Persisted summary must equal authoritative 163.5 hours / $40,875; new/existing detail and calculation rows are covered before redirect reload. |
| CIP .25 development/testing adjustment | 6.7 | `test_cip_scope_quarter_hour_adjustments_and_investment_funding_semantics` | Browser | P0 | **Passing — browser smoke** | .25 development and testing adjustments persist with mandatory notes. |
| CIP Investment funding allocation | Approved funding clarification; supersedes 6.4, 6.8, 9 and Section 15 wording | `test_cip_scope_quarter_hour_adjustments_and_investment_funding_semantics` + `test_investment_funding_invariant.py` + `test_investment_schedule_funding.py` | Browser + domain + integration | P0 | **Passing — browser smoke + deterministic** | 152 gross = 52 Investment + 100 billable; PM, contingency and total effort unchanged; fees reflect billable hours only. |
| Estimate lifecycle lock | 5.1, Section 15 | `test_estimate_lifecycle_locks_ui_and_server_mutation` | Browser | P0 | **Passing — browser smoke** | Draft -> Review -> Approved; locked inputs disabled and server-side mutation rejected. |
| Revision/rebase rationale | 5.1, Section 15 | `test_revision_and_rebase_require_rationale_preserve_source_and_single_working_revision` | Browser | P0 | **Passing — browser release** | Reason mandatory; source immutable; new Draft; one working revision. |
| Configuration SoD and historical pin | 5.2, Section 15 | `test_configuration_separation_of_duties_activation_and_historical_pin` | Browser + integration | P0 | **Passing — browser release** | Preparer self-review blocked; independent approval/activation; prior Active for same product retires; historical estimate pin unchanged. |
| Schedule stale / no implicit regeneration | 7.10, 11, Section 15 | `test_schedule_stale_export_preserves_manual_values_until_explicit_regeneration` | Browser | P0 | **Passing — browser release** | Manual schedule persists; stale warning appears; CSV exports persisted stale rows until explicit regeneration. |
| Jira relationship rules / CSV | 7.11, 11.2, Section 15 | `test_jira_relationship_rules_capacity_cycle_and_csv_mapping` | Browser | P0 | **Passing — browser release** | Self/duplicate/cycle/capacity enforced; exact 27-column CSV populated from persisted explicit relationships only. |
| MEP Net New SOW | 5.3, 14 | `test_mep_net_new_sow_rejection_revision_approval_and_audit` | Browser | P0 | **Passing — browser release** | Controlled rejection/revision/approval and audit. |
| MEP Small Project SOW | 14.3, Section 15 | `test_mep_small_project_full_workflow` | Browser | P0 | **Passing — browser release** | Correct family/template and controlled approval path. |
| CIP Net New + Small Project families | 14, Section 15 | `test_cip_net_new_and_small_project_route_to_correct_sow_families` | Browser | P0 | **Passing — browser release** | Correct family and template pin. |
| PDF/DOCX controls | 14.5, Section 15 | `test_representative_pdf_docx_draft_and_approved_controls` | Browser/document | P0 | **Passing — browser release** | DRAFT/approved treatment; approved content integrity; generated/masked protection secret absent from generated content and logs. |
| Historical config/template/composition | 5, 14.5 | `test_historical_estimate_and_sow_remain_pinned_after_new_config_and_template_activate` | Browser | P0 | **Passing — browser release** | Historical configuration/engine/template/composition pins and approved content remain reproducible after later activation. |
| Audit estimate creation/change | 4.5, Section 15 | existing audit tests + MEP browser journey | Integration/browser | P1 | Existing deterministic coverage + browser evidence | Append-only actor/event evidence. |
| Audit lifecycle | 4.5, Section 15 | lifecycle browser | Browser | P0 | Implemented | Lifecycle behavior is browser-tested; exhaustive audit actor/event/reason validation is not claimed by that browser scenario. |
| Audit revision rationale | 4.5, Section 15 | revision browser | Browser | P0 | **Passing — browser release** | `REVISION_RATIONALE` records reason. |
| Audit config change/review | 4.5, Section 15 | config browser | Browser | P0 | **Passing — browser release** | Create/change/submit/approve/activate evidence. |
| Audit schedule export | 4.5, Section 15 | schedule browser | Browser | P1 | **Passing — browser release** | CSV export event asserted; regeneration audit evidence is not asserted by this browser scenario. |
| Audit Jira mutation | 4.5, Section 15 | Jira browser | Browser | P1 | **Passing — browser release** | Relationship mutation evidence retained. |
| Audit SOW approval/rejection | 4.5, Section 15 | SOW browser | Browser | P0 | **Passing — browser release** | Approval/rejection/revision event types asserted; exhaustive actor/reason checks remain a coverage gap. |
| Cross-browser certification | — | — | Browser | P2 | Gap / Phase 2 | Chromium only by design for Phase 1. |
| Visual pixel regression | — | — | Visual | P2 | Gap / Phase 2 | Not required for Phase 1 functional release gate. |
| Performance/load | — | — | Performance | P2 | Gap / Phase 2 | Outside the Phase 1 functional browser gate. |
| Production synthetic monitoring | — | — | Monitoring | P2 | Gap / intentionally excluded | Destructive browser automation is prohibited against Production. |

## Section 15 coverage

Section 15 is represented explicitly above: MEP/CIP creation, autosave, fractional precision, non-billable treatment, lifecycle locking, revision rationale, configuration separation of duties/activation, schedule staleness, Jira relationship controls, user-role preservation through existing deterministic coverage, SOW self-approval/rejection/template pinning, approved Word fidelity, four-family SOW coverage and access control.

A mapped test does not imply a passing requirement. The current run and exact tested commit are recorded in `PHASE1_VERIFICATION.md` and PR #66.

## Defect resolution

**CI-E2E-DEFECT-001 — specification conflict resolved by the user.** The previous terminology treated “Investment” as customer billable and added non-billable effort. The approved rule instead reallocates existing gross effort between internal Investment and Customer Billable hours. CIP-1.0.2 implements this; prior locked engines retain historical behavior. The obsolete Explain wording assertion now verifies the approved funding rule, with independent 152/52/100 calculation and schedule tests.

**CI-E2E-DEFECT-002 — MEP adjustment summary persistence.** New DetailAdjustment rows were not visible to recalculation because autoflush is disabled. The same issue affected new CalculationAdjustment rows. Both save boundaries now flush before recalculation; four integration cases cover insertion and update and compare all persisted summary values to a fresh authoritative calculation before any page reload. The original browser expectation remains unchanged.

## Remaining evidence gaps

Audit coverage is representative: revision rationale and configuration event sequences are asserted, while exhaustive actor/reason checks and schedule-regeneration audit assertions remain gaps. Phase 1 intentionally does not duplicate every formula, migration, document permutation or Golden scenario in the browser. Cross-browser certification, full visual regression, load/performance testing and Production synthetic monitoring remain outside Phase 1.

The 24-scenario Golden matrix is fixed in source control and never derives its expected values from the application at runtime. Before treating every value as a permanent locked business oracle, each scenario should retain traceable provenance to an approved rule/catalog or previously approved deterministic expected-results baseline. That provenance review is a governance task, not a reason to weaken a failing calculation test.

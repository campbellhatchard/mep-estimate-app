# Automated Test Coverage Matrix

**Governing baseline:** Cloud Inventory Services Estimator No-Code Reconstruction Specification v0.3.25.1 / controlled reconstruction baseline `6f724b7dcce4ae3f798df2e5d0fa661c52a1a171`.

Coverage status is deliberately evidence-based. `Implemented` means an automated test exists. It does not mean the requirement is passing. `Passing` is used only after an executed test demonstrates the expected result. `Blocked — defect` means the test is intentionally left failing because current implementation conflicts with the governing requirement.

| Requirement | Specification section | Test ID | Layer | Criticality | Status | Expected result / current evidence |
|---|---|---|---|---|---|---|
| Active/inactive authentication | 3, 7.1 | `test_authentication_active_and_inactive` | Browser | P1 | **Passing — browser smoke** | Active succeeds; inactive denied through normal authentication. |
| Multi-role / Read Only / Tools Admin | 3 | `test_role_union_readonly_and_tools_admin_boundaries` | Browser | P0 | **Passing — browser smoke** | Union permissions; Read Only controlled mutation denied; Tools Admin cannot access Users. |
| Last active Administrator | 3.3, 12 | `test_last_active_administrator_protection_through_user_ui` | Browser | P0 | Implemented; release run pending | Server refuses removal/deactivation of final active Administrator. |
| MEP product/config/engine pin | 1.3, 6.3 | `test_mep_creation_pins_product_configuration_and_engine` | Browser | P0 | **Passing — browser smoke** | YYYYMMNNN identity, MEP product immutable, configuration and engine pinned. |
| MEP Golden matrix | 8, Appendix A | `test_mep_golden_scenario_matrix` | Golden/domain | P0 | **Passing — deterministic suite** | 12 fixed MEP scenarios. Exact expected values remain independent test-oracle data, not learned during execution. |
| CIP Golden matrix | 9, Appendix B | `test_cip_golden_scenario_matrix` | Golden/domain | P0 | **Passing — deterministic suite** | 12 fixed CIP scenarios. EPP On Prem is tested independently from optional Gateway scope. |
| MEP autosave / ERP reset / .5 adjustment | 6.3, 6.5, Section 15 | `test_mep_autosave_erp_reset_detail_adjustment_and_golden_reload` | Browser + domain invariant | P0 | **Blocked — implementation defect** | Browser autosave and ERP reset/reload succeed; the detail line persists and renders `18.5`, and a fresh authoritative domain calculation returns `163.5` hours / `$40,875`, but the persisted revision summary remains stale at `163.0` hours after Save Detail. See CI-E2E-DEFECT-002. |
| CIP .25 development/testing adjustment | 6.7 | `test_cip_scope_quarter_hour_adjustments_and_nonbillable_semantics` | Browser | P0 | **Passing within browser journey** | .25 development and test adjustments persist with required notes; the same journey then reaches the separate non-billable release blocker below. |
| CIP Plan Hours Not Billable | 6.4, 6.8, 9, Section 15 | `test_cip_scope_quarter_hour_adjustments_and_nonbillable_semantics` | Browser + domain invariant | P0 | **Blocked — implementation defect** | Governing requirement: Plan Hours Not Billable increase internal/Task Hours and **must not increase customer Investment Hours or fees**. Adding 4 controlled non-billable Plan hours increased customer Investment Hours from `262.25` to `263.25`. See CI-E2E-DEFECT-001. |
| Estimate lifecycle lock | 5.1, Section 15 | `test_estimate_lifecycle_locks_ui_and_server_mutation` | Browser | P0 | **Passing — browser smoke** | Draft -> Review -> Approved; locked inputs disabled and server-side mutation rejected. |
| Revision/rebase rationale | 5.1, Section 15 | `test_revision_and_rebase_require_rationale_preserve_source_and_single_working_revision` | Browser | P0 | Implemented; release run pending | Reason mandatory; source immutable; new Draft; one working revision. |
| Configuration SoD and historical pin | 5.2, Section 15 | `test_configuration_separation_of_duties_activation_and_historical_pin` | Browser + integration | P0 | Implemented; release run pending | Preparer self-review blocked; independent approval/activation; prior Active for same product retires; historical estimate pin unchanged. |
| Schedule stale / no implicit regeneration | 7.10, 11, Section 15 | `test_schedule_stale_export_preserves_manual_values_until_explicit_regeneration` | Browser | P0 | Implemented; release run pending | Manual schedule persists; stale warning appears; CSV exports persisted stale rows until explicit regeneration. |
| Jira relationship rules / CSV | 7.11, 11.2, Section 15 | `test_jira_relationship_rules_capacity_cycle_and_csv_mapping` | Browser | P0 | Implemented; release run pending | Self/duplicate/cycle/capacity enforced; exact 27-column CSV populated from persisted explicit relationships only. |
| MEP Net New SOW | 5.3, 14 | `test_mep_net_new_sow_rejection_revision_approval_and_audit` | Browser | P0 | Implemented; release run pending | Controlled rejection/revision/approval and audit. |
| MEP Small Project SOW | 14.3, Section 15 | `test_mep_small_project_full_workflow` | Browser | P0 | Implemented; release run pending | Correct family/template and controlled approval path. |
| CIP Net New + Small Project families | 14, Section 15 | `test_cip_net_new_and_small_project_route_to_correct_sow_families` | Browser | P0 | Implemented; release run pending | Correct family and template pin. |
| PDF/DOCX controls | 14.5, Section 15 | `test_representative_pdf_docx_draft_and_approved_controls` | Browser/document | P0 | Implemented; release run pending | DRAFT/approved treatment; approved content integrity; generated/masked protection secret absent from generated content and logs. |
| Historical config/template/composition | 5, 14.5 | `test_historical_estimate_and_sow_remain_pinned_after_new_config_and_template_activate` | Browser | P0 | Implemented; release run pending | Historical configuration/engine/template/composition pins and approved content remain reproducible after later activation. |
| Audit estimate creation/change | 4.5, Section 15 | existing audit tests + MEP browser journey | Integration/browser | P1 | Existing deterministic coverage + browser evidence | Append-only actor/event evidence. |
| Audit lifecycle | 4.5, Section 15 | lifecycle browser | Browser | P0 | Implemented | Lifecycle actor/event evidence is asserted in deterministic coverage; broader browser audit assertions are in the release suite. |
| Audit revision rationale | 4.5, Section 15 | revision browser | Browser | P0 | Implemented; release run pending | `REVISION_RATIONALE` records reason. |
| Audit config change/review | 4.5, Section 15 | config browser | Browser | P0 | Implemented; release run pending | Create/change/submit/approve/activate evidence. |
| Audit schedule regeneration/export | 4.5, Section 15 | schedule browser | Browser | P1 | Implemented; release run pending | Export/regeneration evidence retained. |
| Audit Jira mutation | 4.5, Section 15 | Jira browser | Browser | P1 | Implemented; release run pending | Relationship mutation evidence retained. |
| Audit SOW approval/rejection | 4.5, Section 15 | SOW browser | Browser | P0 | Implemented; release run pending | Approval/rejection actor and reason evidence. |
| Cross-browser certification | — | — | Browser | P2 | Gap / Phase 2 | Chromium only by design for Phase 1. |
| Visual pixel regression | — | — | Visual | P2 | Gap / Phase 2 | Not required for Phase 1 functional release gate. |
| Performance/load | — | — | Performance | P2 | Gap / Phase 2 | Outside the Phase 1 functional browser gate. |
| Production synthetic monitoring | — | — | Monitoring | P2 | Gap / intentionally excluded | Destructive browser automation is prohibited against Production. |

## Section 15 coverage

Section 15 is represented explicitly above: MEP/CIP creation, autosave, fractional precision, non-billable treatment, lifecycle locking, revision rationale, configuration separation of duties/activation, schedule staleness, Jira relationship controls, user-role preservation through existing deterministic coverage, SOW self-approval/rejection/template pinning, approved Word fidelity, four-family SOW coverage and access control.

A mapped test does not imply a passing requirement. Phase 1 already demonstrates why that distinction matters: two release-critical requirements now have automated coverage and are intentionally red because current implementation does not satisfy the approved behavior.

## Known defects discovered by Phase 1 automation

**CI-E2E-DEFECT-001 — CIP non-billable Plan hours can increase customer fees.**

The v0.3.25.1 specification requires Plan Hours Not Billable to increase internal/Task effort without increasing customer fees. In the controlled browser scenario, adding 4 non-billable hours to Project Kickoff persisted the allocation and increased non-billable/internal effort, but also increased customer Investment Hours from `262.25` to `263.25`. Current Plan PM calculation includes Plan non-billable workload in fee-bearing Investment Hours. This is classified as an **implementation defect**, not a test expectation to be changed.

**CI-E2E-DEFECT-002 — MEP Save Detail leaves the persisted revision summary stale after a fractional detail adjustment.**

The browser successfully changes the ERP-scoped application, records a required-note `0.5` detail adjustment and renders the adjusted line at `18.5` hours. A fresh call to the authoritative v1.0.1 MEP domain calculation returns `163.5` total hours and `$40,875`, proving the calculation domain recognizes the saved adjustment. The persisted `EstimateRevision.calculated_hours` remains `163.0`, however. The Save Detail workflow is therefore not leaving the persisted summary synchronized with the authoritative calculation result required by the controlled workflow. This is classified as an **implementation defect** and remains release-blocking.

Neither defect is suppressed with retries, weakened assertions or alternate expected results. Business behavior must be corrected under normal change control, then these same tests should be rerun unchanged.

## Remaining evidence gaps

Phase 1 intentionally does not duplicate every formula, migration, document permutation or Golden scenario in the browser. Cross-browser certification, full visual regression, load/performance testing and Production synthetic monitoring remain outside Phase 1.

The 24-scenario Golden matrix is fixed in source control and never derives its expected values from the application at runtime. Before treating every value as a permanent locked business oracle, each scenario should retain traceable provenance to an approved rule/catalog or previously approved deterministic expected-results baseline. That provenance review is a governance task, not a reason to weaken a failing calculation test.

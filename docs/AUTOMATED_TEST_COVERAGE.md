# Automated Test Coverage Matrix

**Governing baseline:** Cloud Inventory Services Estimator No-Code Reconstruction Specification v0.3.25.1.

| Requirement | Specification section | Test ID | Layer | Criticality | Status | Expected result / Gap |
|---|---|---|---|---|---|---|
| Active/inactive authentication | 3, 7.1 | `test_authentication_active_and_inactive` | Browser | P1 | Automated | Active succeeds; inactive denied. |
| Multi-role / Read Only / Tools Admin | 3 | `test_role_union_readonly_and_tools_admin_boundaries` | Browser | P0 | Automated | Union permissions; controlled mutation denial; Tools Admin cannot open Users. |
| Last active Administrator | 3.3, 12 | `test_last_active_administrator_protection_through_user_ui` | Browser | P0 | Automated | HTTP 409 and ADMIN unchanged. |
| MEP product/config/engine pin | 1.3, 7.4 | `test_mep_creation_pins_product_configuration_and_engine` | Browser | P0 | Automated | YYYYMMNNN, MEP immutable, config pinned, engine 1.0.1. |
| MEP Golden matrix | 8 | `test_mep_golden_scenario_matrix` | Golden/domain | P0 | Automated | 12 controlled scenarios. |
| CIP Golden matrix | 9 | `test_cip_golden_scenario_matrix` | Golden/domain | P0 | Automated | 12 controlled scenarios. |
| MEP autosave/ERP reset/.5 adjustment | 7.4, 7.6 | `test_mep_autosave_erp_reset_detail_adjustment_and_golden_reload` | Browser | P0 | Automated | Reset/reload; 0.5 persists; controlled result survives reload. |
| CIP .25 adjustments/nonbill | 7.7, 7.9, 9 | `test_cip_scope_quarter_hour_adjustments_and_nonbillable_semantics` | Browser | P0 | Automated with conflict note | Approved v0.3.25.1 includes Plan non-billable workload in Plan PM. The allocation itself is not billed, but PM overhead may move Investment. This conflicts with later wording that Investment/fees must not increase at all; governing baseline behavior is preserved. |
| Estimate lifecycle lock | 5.1 | `test_estimate_lifecycle_locks_ui_and_server_mutation` | Browser | P0 | Automated | Locked server POST fails. |
| Revision/rebase rationale | 5.1, 7.13 | `test_revision_and_rebase_require_rationale_preserve_source_and_single_working_revision` | Browser | P0 | Automated | Rationale, immutable source, one working revision. |
| Configuration SoD and historical pin | 5.2, 7.15 | `test_configuration_separation_of_duties_activation_and_historical_pin` | Browser + integration | P0 | Automated | Self-review blocked; independent reason/approval; same-product retirement; old estimate remains pinned. |
| Schedule stale/no implicit regeneration | 7.10, 11 | `test_schedule_stale_export_preserves_manual_values_until_explicit_regeneration` | Browser | P0 | Automated | Manual values persist and stale CSV exports them; explicit regeneration replaces. |
| Jira relationship rules/CSV | 7.11, 11.2 | `test_jira_relationship_rules_capacity_cycle_and_csv_mapping` | Browser | P0 | Automated | Self/duplicate/cycle/capacity enforced; 27 columns populated from explicit links. |
| MEP Net New SOW | 5.3, 14 | `test_mep_net_new_sow_rejection_revision_approval_and_audit` | Browser | P0 | Automated | Rejection/revision/approval + audit. |
| MEP Small Project SOW | 14.3 | `test_mep_small_project_full_workflow` | Browser | P0 | Automated | Correct family and approval path. |
| CIP Net New + Small Project families | 14.1 | `test_cip_net_new_and_small_project_route_to_correct_sow_families` | Browser | P0 | Automated | Correct family/template pin. |
| PDF/DOCX controls | 14.5 | `test_representative_pdf_docx_draft_and_approved_controls` | Browser/document | P0 | Automated | DRAFT/approved treatment; Track Changes/protection; secret absent. |
| Historical config/template/composition | 14.5 | `test_historical_estimate_and_sow_remain_pinned_after_new_config_and_template_activate` | Browser | P0 | Automated | Historical values and pins unchanged; approved output regenerates. |
| Audit estimate creation/change | Section 15 | existing audit tests + browser MEP journey | Integration/browser | P1 | Automated | Append-only actor/event evidence. |
| Audit lifecycle | Section 15 | lifecycle browser | Browser | P0 | Automated | Submit/approval evidence. |
| Audit revision rationale | Section 15 | revision browser | Browser | P0 | Automated | `REVISION_RATIONALE`. |
| Audit config change/review | Section 15 | config browser | Browser | P0 | Automated | Create/change/submit/approve/activate evidence. |
| Audit schedule regeneration/export | Section 15 | schedule browser | Browser | P1 | Automated | Export/regeneration evidence retained. |
| Audit Jira mutation | Section 15 | Jira browser | Browser | P1 | Automated | `JIRA_RELATIONSHIP_ADDED`. |
| Audit SOW approval/rejection | Section 15 | Net New SOW browser | Browser | P0 | Automated | Rejection/revision/approval events. |
| Cross-browser certification | — | — | Browser | P2 | Gap / Phase 2 | Chromium only by design. |
| Visual pixel regression | — | — | Visual | P2 | Gap / Phase 2 | Not required Phase 1. |
| Performance/load | — | — | Performance | P2 | Gap / Phase 2 | Not part of functional browser gate. |
| Production synthetic monitoring | — | — | Monitoring | P2 | Gap / excluded | Destructive browser automation prohibited against Production. |

## Section 15 audit coverage

Section 15 is explicitly mapped above for estimate creation/change, lifecycle, revision rationale, configuration change/review, schedule regeneration/export, Jira relationship mutation and SOW approval/rejection. Audit remains append-only; no edit/delete utility is added.

## Coverage gaps

Phase 1 intentionally leaves all-browser duplication of every Golden scenario, every document permutation, full visual regression, cross-browser certification, performance/load and Production monitoring outside the browser layer. Existing deterministic tests remain the primary layer where they are more precise.

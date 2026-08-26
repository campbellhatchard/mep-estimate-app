# Four-Family SOW Regression Matrix

This matrix is the release-control map for the four controlled Statement of Work families. It intentionally reuses the established focused Net New tests and adds explicit Small Project lifecycle coverage rather than duplicating equivalent scenarios.

| Control | MEP Net New | CIP Net New | MEP Small Project | CIP Small Project |
|---|---|---|---|---|
| Correct template family / version pinning | `test_zzzb_sow_approval.py`, `test_sow_template_reconcile.py` | `test_zzzz_cip_sow.py` | `test_small_project_sow_workflow.py`, `test_sow_four_family_matrix.py` | `test_small_project_sow_workflow.py`, `test_sow_four_family_matrix.py` |
| Prepare / save / finalize | `test_zzza_sow_queue.py`, `test_zzzb_sow_approval.py` | `test_zzzz_cip_sow.py` | `test_small_project_sow_workflow.py`, `test_sow_four_family_matrix.py` | `test_sow_four_family_matrix.py` |
| Send for approval / assigned queue | `test_zzza_sow_queue.py` | `test_zzzz_cip_sow.py` | `test_sow_four_family_matrix.py` | `test_sow_four_family_matrix.py` |
| No self-approval / self-assignment | shared `sow_routes.py` approval boundary + focused lifecycle tests | shared `sow_routes.py` approval boundary | `test_sow_four_family_matrix.py` explicitly exercises Small Project dispatch through shared boundary | shared boundary exercised by Small Project lifecycle |
| Rejection requires reason | `test_zzzb_sow_approval.py` | shared rejection boundary | `test_sow_four_family_matrix.py` | shared rejection boundary exercised by Small Project dispatch |
| Rejected SOW immutable / new SOW revision | `test_zzzb_sow_approval.py` | shared lifecycle boundary | `test_sow_four_family_matrix.py` | shared lifecycle boundary |
| Draft PDF watermark | `test_controlled_word_sow_v0314.py` shared PDF control | shared PDF control | `test_sow_four_family_matrix.py` | shared PDF control |
| Approved PDF has no Draft watermark | approval/review tests + shared PDF control | `test_zzzz_cip_sow.py` + shared control | shared Small Project renderer/control | `test_sow_four_family_matrix.py` |
| Controlled Word: Track Changes + enforced protection | `test_controlled_word_sow_v0314.py` | controlled Word route + `test_zzzz_cip_sow.py` | `test_sow_four_family_matrix.py` | `test_sow_four_family_matrix.py` |
| Draft Word watermark | `test_controlled_word_sow_v0314.py` | shared controlled Word boundary | `test_sow_four_family_matrix.py` | shared controlled Word boundary |
| Approved Word has no Draft watermark | `test_controlled_word_sow_v0314.py`, `test_zzzc_sow_lock.py` | `test_zzzz_cip_sow.py` | shared controlled Word boundary | `test_sow_four_family_matrix.py` |
| Approval locks content hash / approved snapshot | `test_zzzb_sow_approval.py`, `test_zzzc_sow_lock.py` | `test_zzzz_cip_sow.py` | Small Project approval implementation uses family-specific canonical hash | `test_sow_four_family_matrix.py` |
| Historical approved regeneration / hash fidelity | `test_zzzb_sow_approval.py`, `test_zzzc_sow_lock.py` | `test_zzzz_cip_sow.py` | controlled Word verification boundary | `test_sow_four_family_matrix.py` explicitly recomputes canonical digest/snapshot |
| Product/family route isolation | MEP Net New tests assert MEP renderer/templates | CIP tests reject ineligible family routing | Small Project MEP key asserted in matrix | Small Project CIP key asserted in matrix |

## Release gate

Before a SOW-affecting release is accepted:

1. Run the complete test suite, including `tests/test_sow_four_family_matrix.py`.
2. Run Alembic migrations from a clean database when schema changes are present.
3. Confirm no family can select or mutate another family's controlled template version.
4. Confirm Draft PDF/Word controls and approved Word hash verification remain fail-closed.
5. Verify at least one MEP and one CIP controlled document through the deployed runtime when document-rendering code changes.

## Invariants

- Approved and rejected historical SOWs are immutable.
- Approved wording is hash-bound to the SOW's pinned template/content inputs.
- No uncontrolled editable Word path may be introduced.
- Net New and Small Project families may share lifecycle controls, but family-specific rendering and template selection remain isolated.
- MEP and CIP calculation/SOW composition domains remain product-specific where their business rules differ.

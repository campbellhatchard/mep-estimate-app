# Estimator Application Architecture

## Application bootstrap

`app/run.py` is intentionally a thin production entry point. It imports the legacy FastAPI application object from `app.main` and delegates all release wiring to `app.application_bootstrap.configure_application`.

`application_bootstrap.py` is the single orchestration boundary for release-time registration order. The order is deliberate because several capabilities extend an accepted legacy route and delegate back to the prior endpoint for the product or SOW family they do not own.

The bootstrap is grouped into two explicit domains:

1. **Estimate capabilities** — calculation engine bindings, validation, product-aware MEP/CIP routes, Schedule/Jira exports, calculation/detail previews, revision lifecycle and rationale, assumptions, and controlled draft deletion.
2. **SOW capabilities** — controlled document composition, MEP and CIP Net New routes, four-family template administration, Small Project routing, revision-to-revision SOW lineage, Tools Admin template download, and the final protected Word boundary.

The final bootstrap action calls `assert_final_route_owners(app)`. Startup therefore fails if a shared route is missing, duplicated, or ends up owned by a different module than the architecture contract expects.

## Module ownership

| Capability | Primary module(s) | Ownership rule |
| --- | --- | --- |
| Legacy MEP data model and base FastAPI routes | `app.main` | Foundation only; later product-aware layers may replace shared routes but must preserve MEP behavior. |
| Route interception and final ownership contract | `app.route_architecture` | Only module permitted to manipulate `app.router.routes` directly. |
| Product identity and CIP domain helpers | `app.cip_domain`, `app.cip_models` | Business-domain/product resolution. Route interception is imported from `route_architecture`; it is no longer implemented in the CIP domain. |
| MEP/CIP repository and estimate authoring dispatch | `app.cip`, `app.cip_routes_repository`, `app.cip_routes_estimate`, `app.cip_routes_detail` | One final endpoint per shared estimate route; delegates to accepted MEP behavior when product is MEP. |
| MEP/CIP Schedule generation | `app.application_bootstrap`, `app.services.schedule`, `app.services.cip_schedule` | Bootstrap exposes one product-aware `core.generate_schedule`; existing product formulas remain in their service modules. |
| Schedule CSV and Jira export | `app.schedule_exports_runtime` | Reads persisted Schedule rows; Jira may generate only when no persisted Schedule exists. |
| Revision lifecycle | `app.revision_history`, `app.estimate_revision_controls` | `revision_history` owns status transitions; `estimate_revision_controls` owns revision rationale/history and final new-revision route. |
| MEP SOW foundation | `app.sow_routes`, `app.sow_service` | Shared lifecycle controls plus MEP Net New rendering. |
| CIP Net New SOW specialization | `app.cip_sow.*` | Product-specific authoring/rendering while delegating MEP SOWs to the foundation routes. |
| Small Project SOW specialization | `app.sp_routes_b`, `app.sp_core_*`, `app.sp_render_*` | Dispatches MEP/CIP Small Project families and delegates Net New families to prior handlers. |
| SOW lineage across Estimate revisions | `app.sow_lineage_runtime` | Final wrapper around SOW creation only; preserves compatible user-authored content without copying revised estimate commercials. |
| Four-family SOW template administration | `app.small_project_template_admin` | Final admin GET/upload/activation routes for all four families. |
| Controlled Word generation | `app.sow_word_control`, `app.small_project_word_runtime` | `sow_word_control` owns the final `/sow/{sid}/docx` boundary for all families; Small Project extends the raw renderer selection without replacing protection controls. |
| Tools Admin template download | `app.tools_admin_runtime` | Final controlled SOW template download route. |
| Configuration data | `app.cip_routes_config`, existing MEP configuration models | Product-aware Calculation Data administration while retaining estimate configuration pinning. |

## Shared route ownership

`app.route_architecture.FINAL_ROUTE_OWNERS` is executable documentation for the shared endpoints whose registration order previously existed only implicitly in `run.py` comments.

Important final ownership examples include:

- `/estimates/new` POST → `app.cip_routes_repository` for MEP/CIP creation dispatch.
- `/estimate/{rid}/new-revision` POST → `app.estimate_revision_controls` for required revision rationale plus shared revision creation.
- `/estimate/{rid}/jira.csv` and `/estimate/{rid}/schedule.csv` → `app.schedule_exports_runtime`.
- `/estimate/{rid}/sow` and the core SOW page/save/finalize/approve/PDF routes → `app.sp_routes_b`, which is the four-family dispatcher.
- `/estimate/{rid}/sow/create` POST → `app.sow_lineage_runtime`, the final creation wrapper after product/family dispatch.
- `/sow/{sid}/send-approval` and `/sow/{sid}/reject` → `app.sow_routes`, because those lifecycle controls are intentionally shared across all families.
- `/sow/{sid}/docx` → `app.sow_word_control`, the single protected Microsoft Word boundary.
- SOW template administration → `app.small_project_template_admin`, with template download finalized by `app.tools_admin_runtime`.

Route replacement itself uses `route_architecture.take_route`. It preserves the established delegation model but now rejects ambiguous duplicate registrations instead of silently removing whichever matching route appears first.

## Historical reproducibility invariants

This refactor must not alter business calculations, approved document wording, or historical regeneration semantics. The following invariants remain release gates:

- Locked Estimate revisions continue to use their persisted engine/composition version and pinned configuration.
- MEP and CIP calculation formulas remain in their existing calculation service modules; bootstrap changes wiring only.
- Approved SOWs remain pinned to the specific `SOWTemplateVersion` used when the SOW was created.
- `composition_version` continues to control version-gated document wording so later renderer enhancements do not retroactively change historical SOWs.
- Approved SOW downloads must regenerate to the stored canonical content hash or be blocked for audit safety.
- The four controlled families — MEP Net New, CIP Net New, MEP Small Project, CIP Small Project — must continue to pass the explicit four-family lifecycle/document/routing matrix.
- Draft and approved Word controls, PDF review watermarking, no-self-approval, required rejection reason, and rejected-SOW revision controls remain unchanged.
- Schedule/Jira exports continue to operate from persisted Schedule rows under the v0.3.20 contract.

## Change discipline

Future functional work should register new capability ownership deliberately rather than adding an untracked route interception layer. If a new module replaces a shared route, update `FINAL_ROUTE_OWNERS`, the architecture documentation, and regression coverage in the same pull request.

Architecture cleanup must not be used as an opportunity to change commercial calculations, customer-facing SOW wording, approval rules, or historical regeneration behavior. Those changes require separate functional issues and release evidence.

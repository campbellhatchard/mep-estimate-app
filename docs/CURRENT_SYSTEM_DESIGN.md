# Current System Design — Cloud Inventory Services Estimator

**Status:** Authoritative current design record  
**Production release:** v0.3.14.1  
**Runtime entry point:** `app.run:app`  
**Supersedes for current-state decisions:** the original workbook-era `docs/DESIGN_SPEC.md`

## 1. Purpose

The Cloud Inventory Services Estimator is a controlled web application for estimating professional-services engagements for two products:

- **MEP — Mobile Enterprise Platform**
- **CIP — Cloud Inventory Platform**

The application replaces spreadsheet-only estimating with deterministic calculation engines, configuration governance, estimate revisions, auditability, lifecycle approvals, schedules, exports and controlled Statement of Work (SOW) generation.

The design objective is not simply to reproduce spreadsheet formulas. It is to preserve approved business behavior while making configuration, calculation rules, manual overrides and historical revisions explicit and reproducible.

## 2. Current baseline and compatibility contract

The accepted production release is **v0.3.14.1**. Current `main` is that accepted release plus a dead-code-only cleanup merged in PR #21.

The following are compatibility controls:

1. New/editable MEP revisions use calculation engine **1.0.1**.
2. New/editable CIP revisions use calculation engine **CIP-1.0.1**.
3. Locked historical revisions retain their historical pinned calculation semantics rather than being silently recalculated under a newer engine.
4. Estimate revisions remain pinned to their configuration version.
5. SOWs remain pinned to their SOW template version.
6. Approved SOW wording is protected by canonical-text SHA-256 and an approved-text snapshot.
7. Existing Net New MEP/CIP SOW behavior must not be changed as a side effect of future Small Project work.

## 3. Technology and deployment

The current stack is:

- Python 3.12
- FastAPI
- SQLAlchemy
- Alembic
- Jinja server-rendered UI
- PostgreSQL in production
- SQLite for local/test use
- ReportLab/PyPDF for PDF-related output/control
- python-docx/Open XML manipulation for controlled Word output
- GitHub source control and GitHub Actions CI
- Render web service + Render PostgreSQL

`render.yaml` is the deployment contract. The web service deploys from `main`, runs `alembic upgrade head` before startup and launches `uvicorn app.run:app`.

## 4. Runtime composition

`app/run.py` is the production composition root. It layers the accepted capabilities in a deliberate order so shared routes and historical behavior remain stable.

Major runtime responsibilities include:

- shared application/template configuration;
- calculation precision installation;
- MEP product routes;
- CIP product registration and dispatch;
- live calculation/detail preview;
- revision lifecycle;
- assumptions;
- controlled Draft estimate deletion;
- SOW signature/presentation controls;
- SOW template reconciliation;
- MEP SOW registration;
- CIP SOW registration;
- shared controlled Word interception registered last.

Registration order is a compatibility boundary. Future work should prefer explicit product/family dispatch over broad route interception.

## 5. Domain control model

The application separates four categories of business behavior:

### 5.1 Estimate inputs

Customer/project-specific selections and quantities entered on the Estimate and related pages.

### 5.2 Versioned configuration

Administrator-controlled values and catalogs that can change over time without changing calculation source code. Revisions are pinned to a configuration version.

### 5.3 Source-controlled calculation rules

Deterministic MEP/CIP calculation logic. Calculation rules are not arbitrary administrator-editable formulas.

### 5.4 Estimate-level overrides

Manual adjustments are stored separately from standard/calculated values and are auditable. Required notes/reasons are enforced where applicable.

This separation is a core control principle and should not be collapsed in future enhancements.

## 6. Estimate lifecycle and revision behavior

The estimate lifecycle is controlled around Draft, Review/approval and historical locking. Approved/final/superseded revisions are not directly edited.

A later change requires a new revision. Rebase-to-current-model creates a new revision pinned to the current active configuration while preserving the source revision as historical evidence.

Draft estimate deletion is available only under the controlled eligibility rules implemented in the accepted application; it is not a general hard-delete capability for controlled historical revisions.

## 7. MEP estimating

MEP retains the workbook-aligned operating model:

- Estimate
- Estimate Detail
- Calculations
- Schedule
- Audit
- Calculation Data
- PDF/Jira outputs

ERP selection controls the applicable application/package catalog. Calculation-driving changes and live preview use the same corrected calculation path used by Save.

### MEP calculation engine

`app/services/calculation_v101.py` defines engine version **1.0.1** for editable/new revisions. It preserves fractional adjustments using decimal half-up precision while routing older locked revisions to the historical calculation implementation where required.

## 8. CIP estimating

CIP is an independent estimating product sharing common application controls but using its own scope/domain and calculation path.

CIP includes product-specific inputs for desktop/mobile scope, integrations, reporting, labels, REST/Boomi and testing factors, plus CIP-specific detail, phase calculations, schedule and exports.

### CIP calculation engine

`app/services/cip_calculation_v101.py` defines engine version **CIP-1.0.1** for editable/new revisions and preserves historical CIP behavior for locked older revisions.

MEP and CIP configuration/calculation ownership must remain isolated even where UI or workflow infrastructure is shared.

## 9. Schedule and exports

The generated Schedule is derived from estimate/calculation data but is not intended to become a full project-management system.

Manual schedule edits are preserved until the user explicitly regenerates the schedule. Regeneration can replace manual schedule work and therefore must remain an explicit action.

Current output boundaries include structured PDF estimate output and Jira CSV export. Jira dependency/linking remains a future integration concern rather than a reason to alter core schedule domain data.

## 10. User roles and security controls

Current roles include:

- Administrator
- Estimator
- Reviewer
- Approver
- SOW Approver
- Read Only

Users can hold valid role combinations. Authentication is case-insensitive for username matching while display capitalization is retained. Users have Active/Inactive status and administrators can reset passwords.

Production secrets include at least:

- `SESSION_SECRET`
- `ADMIN_PASSWORD`
- `SOW_TRACK_CHANGES_PASSWORD`

Secrets must remain environment-managed and must not be committed to source control.

## 11. Net New SOW architecture

MEP Net New and CIP Net New SOWs are production capabilities.

The controlled lifecycle is:

`DRAFT -> FINALIZED -> PENDING_APPROVAL -> APPROVED / REJECTED`

Key controls:

- SOW template versions use Draft/Active/Retired lifecycle.
- Each SOW pins a specific template version.
- Approval is assigned to a SOW Approver.
- Self-approval is prohibited.
- Rejection requires a reason.
- A rejected SOW is immutable; continued work creates a new SOW revision.
- Approval records canonical substantive text and SHA-256 content hash.
- Historical approved Word regeneration verifies controlled approved content.

### PDF review

Non-approved SOW review PDFs are visibly watermarked **DRAFT**. Approved review PDFs are clean.

### Controlled Microsoft Word

Word output is available in every SOW state through one shared control boundary registered after MEP and CIP SOW routing.

Current Word controls include:

- non-approved Word documents carry a DRAFT watermark;
- controlled headers/footers and page information;
- reconciled TOC/page presentation;
- Track Changes enabled and password-enforced using `SOW_TRACK_CHANGES_PASSWORD`;
- no intentional pre-existing tracked revisions in the generated baseline document;
- approved Word generation remains subject to approved-content verification.

## 12. SOW template families

Production `main` currently implements the controlled Net New families:

- MEP Net New
- CIP Net New

The target architecture will contain four independent template families after Small Project foundation work:

- MEP Net New
- CIP Net New
- MEP Small Project
- CIP Small Project

Activation/retirement must operate within the same template family only. Historical SOWs remain pinned to the version used when prepared.

## 13. Small Project SOW — planned, not production

Small Project SOW authoring is intentionally **not** on current `main`.

The implementation is being rebuilt from the accepted v0.3.14.1 baseline rather than merging earlier mixed branches. The intended development order is:

1. Small Project template/domain foundation;
2. Small Project authoring/workflow;
3. four-family SOW regression matrix.

Controlled Small Project source DOCX files must be stored as real binary assets and verified by SHA-256. Fragmented Base64 text-file packaging is not an accepted production pattern.

The current roadmap is tracked in GitHub Issues #22, #23 and #24.

## 14. Persistence and auditability

Production business data is stored in PostgreSQL and migrated through Alembic. The Render service filesystem is not a durable system of record.

Audit events are append-only application records covering controlled estimate/configuration/SOW actions and outputs. Future features must preserve auditability when they introduce new approval, override or document-generation events.

## 15. Migration rules

All schema changes must use Alembic and form one valid migration chain from the current production head.

Release validation must include a clean migration test against an empty database. A feature requiring schema change must also consider upgrade behavior from the accepted production schema and must not reuse obsolete migration IDs from abandoned branches.

## 16. Source control and release rules

The intended repository workflow is:

1. branch from current `main`;
2. keep a branch/PR focused on one coherent change;
3. preserve accepted baseline behavior through regression tests;
4. require GitHub Actions to pass;
5. merge through a PR rather than direct feature pushes to `main`;
6. retain accepted baseline branches where useful;
7. close/delete obsolete branches once their useful history is represented elsewhere.

Old branches are historical evidence, not alternative sources of truth.

## 17. Current technical debt

Known technical debt includes:

- FastAPI startup-event deprecations;
- `datetime.utcnow()` deprecations;
- Starlette template-response signature deprecations;
- SQLAlchemy identity-map warnings in some replacement/rebuild flows;
- accumulated runtime layering that should eventually be consolidated without changing business behavior.

These items are tracked separately so they are not mixed into functional Small Project work.

## 18. Repository governance decisions requiring GitHub settings

Two repository-level controls cannot be inferred from application code and must be deliberately maintained in GitHub:

1. **Protect `main`** with pull-request and required-status-check enforcement and no force pushes.
2. **Repository visibility:** the repository is currently public. Before committing proprietary commercial templates or other sensitive controlled artifacts, confirm that public visibility is intentional; otherwise make the repository private first.

## 19. Deferred enterprise roadmap

Deferred work includes:

- two-person configuration approval governance;
- CRM integration;
- enterprise SSO;
- historical spreadsheet import if still required;
- Jira dependency/link mapping;
- broader external project-management integration.

These items should be implemented from GitHub Issues rather than by reviving old branches.

## 20. Authority order

For current-state decisions, use the following precedence:

1. accepted production code on `main`;
2. current automated regression tests;
3. `docs/CURRENT_SYSTEM_DESIGN.md`;
4. `docs/BUILD_AND_RELEASE_GATES.md`;
5. active GitHub Issues/accepted PR requirements;
6. historical design documents and obsolete branches.

Historical material remains useful for traceability but must not silently override the accepted current architecture.

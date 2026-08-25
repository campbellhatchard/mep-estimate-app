# Cloud Inventory Services Estimator

This repository contains the controlled estimating application for Cloud Inventory professional-services engagements. It supports both **Mobile Enterprise Platform (MEP)** and **Cloud Inventory Platform (CIP)** estimating, revision governance, approvals, schedules, exports and controlled Statement of Work generation.

## Current production baseline

- Application release: **v0.3.14.1**
- Accepted release branch: `baseline/v0.3.14.1-accepted`
- Current `main` includes the accepted v0.3.14.1 release plus PR #21's dead-code-only Small Project scaffolding cleanup.
- Runtime entry point: `app.run:app`
- MEP calculation engine for editable/new revisions: **1.0.1**
- CIP calculation engine for editable/new revisions: **CIP-1.0.1**
- Locked historical revisions preserve their pinned historical calculation behavior.

`main` is the source for new development. Do not revive or merge obsolete feature branches simply because they contain earlier implementations of a capability.

## Implemented capability

### Shared estimating controls

- Product-aware MEP/CIP estimate repository and immutable product selection.
- Monthly estimate numbering and revision history.
- Draft/Review/Approved/Superseded estimate lifecycle.
- Configuration versions with Draft/Active/Retired lifecycle and immutable revision pinning.
- Explicit rebase to the current active configuration through a new revision.
- Append-only audit events.
- Multi-role user administration including Administrator, Estimator, Reviewer, Approver, SOW Approver and Read Only.
- Case-insensitive username authentication, active/inactive users and administrator password reset.
- Draft estimate deletion under controlled eligibility rules.
- In-application blocking error modal behavior.

### MEP estimating

- Workbook-aligned Estimate, Estimate Detail, Calculations and Schedule workflows.
- ERP-aware application/package catalogs.
- Live calculation/detail preview using the same corrected calculation engine used by Save.
- Fractional adjustment precision through MEP calculation engine 1.0.1.
- PDF estimate output and Jira CSV export.

### CIP estimating

- Independent CIP configuration, release catalog, scope/domain model and calculation path.
- Desktop, Mobile, integrations, reporting, labels, REST/Boomi and testing inputs.
- CIP Estimate Detail, phase calculations, schedule, PDF and Jira CSV output.
- Fractional adjustment precision through CIP calculation engine CIP-1.0.1.

### Net New SOW workflow

MEP Net New and CIP Net New SOWs are implemented and controlled through a shared lifecycle:

`DRAFT -> FINALIZED -> PENDING_APPROVAL -> APPROVED / REJECTED`

Controls include:

- assigned SOW Approver and no self-approval;
- mandatory rejection reason;
- immutable rejected SOWs with new-revision creation;
- versioned/pinned SOW templates;
- PDF review inside the application;
- **DRAFT** watermarking for non-approved review PDFs;
- Microsoft Word download in every SOW state;
- **DRAFT** Word watermarking for non-approved SOWs;
- password-enforced Microsoft Word Track Changes;
- approved-content canonical-text SHA-256 and approved text snapshot;
- verification before approved Word regeneration;
- controlled Word header/footer, pagination and TOC reconciliation.

## Not yet on `main`

**Small Project SOW authoring is not implemented on the production baseline.** It is being rebuilt cleanly from v0.3.14.1 rather than merging the obsolete mixed Small Project branches.

Track that work in:

- Issue #22 — v0.3.15 Small Project SOW Foundation
- Issue #23 — Small Project SOW Authoring and Workflow
- Issue #24 — Four-Family SOW Regression Matrix

The controlled MEP and CIP Small Project source DOCX assets must be stored as real binary Git assets with SHA-256 verification. Do not restore the previous fragmented Base64 asset approach.

## Authoritative documentation

- `docs/CURRENT_SYSTEM_DESIGN.md` — current architecture and functional control model.
- `docs/BUILD_AND_RELEASE_GATES.md` — build, test, migration, PR and release requirements.
- `docs/DESIGN_SPEC.md` — original MEP workbook-era design record; retained for historical traceability only.
- `docs/BUILD_VALIDATION.md` — current validation summary and pointer to the release gates.

When documentation conflicts, `CURRENT_SYSTEM_DESIGN.md`, `BUILD_AND_RELEASE_GATES.md`, current automated tests and the accepted production code take precedence over historical design documents.

## Local development

Python 3.12+ is recommended.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.run:app --reload
```

Required/important environment variables:

```text
DATABASE_URL
SESSION_SECRET
ADMIN_PASSWORD
SOW_TRACK_CHANGES_PASSWORD
```

For local development, SQLite is supported. Production uses PostgreSQL.

Run the complete test suite with:

```bash
PYTHONPATH=. pytest -q
```

GitHub Actions additionally validates a clean Alembic upgrade and explicit SOW release-gate scenarios.

## Render deployment

`render.yaml` defines the GitHub-to-Render deployment contract:

- branch: `main`
- automatic deploy on commit
- build: `pip install -r requirements.txt`
- pre-deploy: `alembic upgrade head`
- start: `uvicorn app.run:app --host 0.0.0.0 --port $PORT`
- health check: `/health`
- durable PostgreSQL database

Do not rely on the Render web-service filesystem for persistent business data.

## Repository and release governance

New work should follow this pattern:

1. start from current `main`;
2. use one focused feature/hotfix/chore branch;
3. do not mix unrelated business changes into one PR;
4. run migration and regression checks through GitHub Actions;
5. merge only after the PR is green and the requested behavior is accepted;
6. create/retain a baseline branch for accepted releases where appropriate;
7. delete obsolete merged branches after their history is safely represented on `main`.

`main` should be protected in GitHub settings with pull-request and required-status-check enforcement. The repository is currently public; before committing proprietary controlled commercial templates or other sensitive artifacts, confirm that public visibility is intentional or change the repository to private.

## Deferred roadmap

The tracked backlog includes Small Project SOW, four-family SOW regression, architecture consolidation, CI/deprecation cleanup, configuration approval governance, CRM integration, enterprise SSO and related enterprise integration work. GitHub Issues are the authoritative backlog for future implementation work.

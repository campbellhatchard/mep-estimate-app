# Cloud Inventory MEP Estimate Application

This repository contains the first runnable application build that replaces the approved `Estimate_2026_MEP_18` Excel workbook with a controlled, auditable web application.

## Current build scope

Implemented:

- Workbook-aligned **Estimate** page with approved dropdown values and ERP-specific application/package catalogs.
- **Estimate Detail** with Base Hours, editable Mod Hours, Unit Testing, Notes, totals, and audited Unit Testing Factor override.
- **Calculations** by Plan, Design, Build, Test, and Go Live with editable Standard Adjust and mandatory adjustment notes.
- **Schedule** generated from the estimate, spreadsheet-style planning grid, editable resource/status/% complete/change order/hours used/comments/dates, and Gantt timeline.
- Schedule staleness warning and explicit regeneration so manual schedule edits are never silently overwritten.
- Searchable **Calculation Data** area, viewable by all and editable by Administrators in Draft configuration versions.
- Configuration lifecycle: Draft -> Active -> Retired, with schema fields reserved for future reviewer/approver workflow.
- Immutable estimate/configuration pinning. Existing revisions retain their original configuration. Explicit **Rebase to Current Model** creates a new revision.
- Estimate lifecycle: Draft -> Review -> Approved -> Superseded.
- Roles: ADMIN, ESTIMATOR, REVIEWER, APPROVER, READ_ONLY.
- Case-insensitive username authentication while preserving display capitalization.
- Append-only audit events for estimate, detail, calculations, schedule, configuration, lifecycle, and exports.
- PDF estimate generation.
- Jira CSV export generated from Schedule using the approved workbook's complete 27-column header structure. Dependency/link columns are reserved for later relationship mapping; Parent/Epic hierarchy is populated in v1.
- PostgreSQL production database; SQLite supported for local development.
- Alembic schema migrations.
- Render Blueprint (`render.yaml`) for GitHub -> Render deployment.
- Automated workflow tests.

## Important control principle

The application separates:

1. **Inputs** — estimate-specific selections.
2. **Configuration values/factors** — Administrator controlled and versioned.
3. **Calculation rules** — software controlled and regression tested.
4. **Estimate-level overrides** — separately stored, visibly identified, and audited.

Material numeric assumptions from the workbook have been externalized into the initial configuration model rather than left as hidden source-code constants.
Required calculation parameters do **not** have business-value fallbacks in source code; a missing required configuration value fails explicitly rather than silently changing the estimate.

## Local run

Python 3.12+ is recommended.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

### Initial Administrator

If no users exist, the application creates:

- Username: `Admin`
- Password: value of environment variable `ADMIN_PASSWORD`

For local development only, if `ADMIN_PASSWORD` is absent, the fallback is `ChangeMe123!`. Do not use that fallback in a shared environment.

Example:

```bash
export ADMIN_PASSWORD='replace-with-a-strong-password'
export SESSION_SECRET='replace-with-a-long-random-secret'
```

Windows PowerShell:

```powershell
$env:ADMIN_PASSWORD = 'replace-with-a-strong-password'
$env:SESSION_SECRET = 'replace-with-a-long-random-secret'
```

## Tests

```bash
PYTHONPATH=. pytest -q
```

The current suite validates:

- case-insensitive authentication;
- estimate creation and recalculation;
- rendering of Estimate, Estimate Detail, Calculations, Schedule, Audit, Calculation Data, and Users;
- PDF and Jira CSV output;
- adjustment-note enforcement and audit events;
- configuration-version immutability and explicit rebase;
- Approved revision locking.

## Render deployment

The repository includes `render.yaml`.

1. Push this repository to the GitHub repository that will host the application.
2. In Render, create a Blueprint from that repository.
3. Set the `ADMIN_PASSWORD` secret when prompted.
4. Render creates the web service and PostgreSQL database.
5. Alembic runs as the pre-deploy migration command.
6. The application seeds the approved initial configuration and Administrator on first startup.

The database is the durable system of record. Do not rely on the Render web-service filesystem for persistent application data.

## Source workbook controls

The supplied workbook remains the approved initial business source model. It contains known broken named references and several spreadsheet defects. The application therefore does **not** blindly execute Excel formulas. The extracted rule inventory and original formulas are retained under `docs/` for parity review.

Before Production approval, complete the Golden Scenario validation described in `docs/PARITY_AND_RELEASE_GATE.md`.

## Repository structure

```text
app/
  main.py                    FastAPI routes and workflow
  models.py                  SQLAlchemy domain model
  database.py                Database setup
  auth.py                    Authentication/authorization
  seed.py                    Initial approved configuration
  services/
    calculation.py           Deterministic estimate engine
    schedule.py              Estimate -> Schedule generator
    audit.py                 Append-only audit event helper
  seed/
    approved_model_2026_08_1.json
    schedule_template_2026.json
  templates/                 Workbook-aligned server-rendered UI
  static/app.css
migrations/                  Alembic migrations
tests/                       Automated workflow tests
docs/                        Design, workbook inventory, rule/config catalogs
render.yaml                  Render Blueprint
```

## Explicit future items

Architected but not implemented in this build:

- two-person configuration reviewer/approver enforcement;
- CRM API integration;
- SOW template/content generation;
- enterprise SSO;
- historical Excel estimate import;
- live project-management functionality beyond generated estimate Schedule.

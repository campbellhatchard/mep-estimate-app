# Automated Testing Architecture — Cloud Inventory Services Estimator

**Baseline:** v0.3.25.1 / `6f724b7dcce4ae3f798df2e5d0fa661c52a1a171`

## Objective

Add a lightweight real-browser layer without changing Production architecture. Existing deterministic tests remain authoritative for formulas, Golden parity, migrations, RBAC, lifecycle, Schedule/Jira, SOW controls and historical reproducibility. Playwright proves that selected release-critical user journeys connect the rendered browser UI to the same FastAPI, authorization, SQLAlchemy, PostgreSQL and server-authoritative domain logic.

## Testing layers

1. **Deterministic/unit/domain** — normal `pytest`; authoritative for MEP/CIP calculations and rounding.
2. **Integration/regression** — existing FastAPI TestClient/database suites.
3. **Golden** — 24 static controlled scenarios in `tests/golden/expected_v03251.json`; expected results are not generated from current application output.
4. **Browser E2E** — Python `pytest-playwright` + Playwright, Chromium only in Phase 1.

## Environment strategy

Normal development remains unchanged. Browser tooling is isolated in `requirements-e2e.txt`. GitHub Actions Browser Tests use an ephemeral **PostgreSQL 18** service container, Alembic, and the checked-out Uvicorn application on localhost. The database and runner disappear after the job.

No Render test service, permanent test database, Production environment variable or Production Playwright/browser dependency is introduced.

## Production safety

Phase 1 E2E accepts only `localhost` or `127.0.0.1`; `Unsafe E2E target` terminates any other host. Browser CI never references the Production URL.

## Synthetic data

Fixed synthetic ADMIN, TOOLS_ADMIN, ESTIMATOR, REVIEWER, APPROVER, SOW_APPROVER, READ_ONLY, multi-role and inactive users are created only in the isolated database. There is no authentication bypass: tests log in through `/login`.

## Browser suites

PRs run `pytest tests/e2e -m smoke`. Push to `main` and manual Browser Tests run `pytest tests/e2e -m release`. Smoke cases are also marked release. Retries are zero.

Failure evidence includes the Playwright trace, screenshot, pytest output and application log. Video is intentionally off.

## Commands

Normal deterministic testing needs no browser:

```bash
pytest
```

After installing `requirements-e2e.txt`, Chromium, migrating an isolated DB and starting the app:

```bash
pytest tests/e2e
pytest tests/e2e -m smoke
pytest tests/e2e -m release
```

## Golden strategy

The v0.3.25.1 Golden matrix has 12 MEP + 12 CIP scenarios spanning Net New, Install Base, Small Project, EPP, platform move, application/package/components, UAT, markup, Desktop/Mobile/custom/report/label/Boomi/REST, testing modifiers and internal non-billable treatment. A mismatch is classified as implementation defect, obsolete test, specification conflict or unresolved business-rule decision; expected values are not changed merely to make the implementation green.

## CI release gate

The existing `Application Tests` workflow remains authoritative and separate. Browser Tests provision PostgreSQL 18, run Alembic, install Chromium, start `uvicorn app.run:app`, wait for `/health`, seed synthetic users, run smoke/release and upload failure artifacts.

## Intentional browser exclusions

Browser automation does not duplicate every formula, Golden scenario, migration or document XML assertion. Cross-browser certification, AI test selection, pixel comparison, load/performance testing and Production synthetic monitoring are outside Phase 1.

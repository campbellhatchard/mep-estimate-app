# Automated Testing Architecture — Cloud Inventory Services Estimator

**Baseline:** v0.3.25.1 / `6f724b7dcce4ae3f798df2e5d0fa661c52a1a171`

## Objective

Add a lightweight real-browser validation layer without changing Production architecture. Existing deterministic tests remain the primary authority for formulas, rounding, migrations, RBAC, lifecycle, Schedule/Jira, SOW controls and historical reproducibility. Playwright proves that selected release-critical user journeys connect the rendered browser UI to the same FastAPI, authorization, SQLAlchemy, PostgreSQL and server-authoritative calculation domain used by the deployed application.

The browser layer is a release detector, not a second calculation engine. When a browser or Golden test exposes disagreement between the approved specification, controlled expected-results baseline, existing deterministic tests and current implementation, the discrepancy is classified and reported rather than hidden by changing the assertion.

## Testing layers

1. **Deterministic/unit/domain** — normal `pytest`; authoritative for MEP/CIP formulas, rounding and low-level business invariants.
2. **Integration/regression** — existing FastAPI TestClient/database suites covering authorization, migrations, lifecycle, exports, SOW controls and persistence.
3. **Golden/domain parity** — 24 fixed Phase 1 scenarios in `tests/golden/expected_v03251.json` (12 MEP + 12 CIP). Expected values are source-controlled and are never calculated from the application's current runtime output during test execution. Scenario-by-scenario provenance should remain traceable to approved v0.3.25.1 rules/catalogs or a previously approved deterministic expected-results baseline.
4. **Browser E2E** — Python `pytest-playwright` + Playwright, Chromium only in Phase 1, exercising selected highest-risk journeys through a real running HTTP application and PostgreSQL database.

## Requirements precedence

Automation follows this authority order:

1. Current approved functional specification, presently v0.3.25.1, including the approved [Investment funding clarification](INVESTMENT_FUNDING_CLARIFICATION.md).
2. Locked/approved Golden expected results and calculation-rule catalogs.
3. Existing deterministic automated regression tests.
4. Current application implementation where consistent with 1-3.

A failing test is not automatically a bad test. If current implementation conflicts with the approved requirement, the test remains strict and the product discrepancy is recorded as an implementation defect.

## Environment strategy

Normal development remains unchanged. Browser tooling is isolated in `requirements-e2e.txt`; it is not part of `requirements.txt` or Render build/runtime configuration.

GitHub Actions Browser Tests use an ephemeral **PostgreSQL 18** service container, apply Alembic migrations, start the checked-out Uvicorn/FastAPI application on localhost, seed synthetic controlled users/data, install Playwright Chromium in the Actions runner, execute the selected browser suite and discard the runner/database afterward.

No additional Render service, permanent test database, JavaScript/Node test stack, Production environment variable or Production Playwright/browser dependency is introduced.

SQLite remains appropriate for the existing fast local/unit suites where repository architecture already permits it. PostgreSQL-backed browser/integration validation is used where database semantics and the deployed application path matter.

## Production safety

Phase 1 E2E accepts only `localhost` or `127.0.0.1`; any other `E2E_BASE_URL` terminates collection with `Unsafe E2E target`. Browser CI never references the Production URL and no destructive browser scenario may run against Production.

## Synthetic data and authentication

Fixed synthetic ADMIN, TOOLS_ADMIN, ESTIMATOR, REVIEWER, APPROVER, SOW_APPROVER, READ_ONLY, multi-role and inactive users are created only in the isolated automated-test database. Tests authenticate through the normal `/login` route; there is no test-only login bypass and no authorization guard is weakened for automation.

Synthetic estimates, revisions, configurations, schedules, Jira relationships and SOWs are created as required. No production customer record is a test dependency.

The SOW Track Changes protection secret used by browser CI is generated uniquely for the runner, masked before subsequent steps and never committed as a static value. Output tests verify that the runtime secret is not embedded in generated DOCX XML.

## Browser suites

### Smoke

PR validation runs `pytest tests/e2e -m smoke`. Smoke focuses on fast release signals:

- active/inactive authentication;
- representative role boundaries;
- MEP identity/config/engine pinning;
- MEP autosave, ERP reset/reload and .5 detail precision;
- CIP .25 detail precision and the approved Investment funding invariant;
- lifecycle locking including server-side mutation rejection.

### Release

Every run executes the six smoke tests first. Pushes to `main`, explicit Browser Tests runs, and PRs carrying the `full-release-tests` label then execute `pytest tests/e2e -m "release and not smoke"` only if smoke passes. Ordinary PRs remain smoke-only. Adding or removing that label also triggers validation. Release adds:

- final Administrator protection;
- revision/rebase rationale and single working revision;
- configuration separation of duties, activation and historical estimate pinning;
- schedule stale/no-implicit-regeneration behavior;
- Jira relationship validation and exact export mapping;
- representative Net New and Small Project SOW workflows;
- PDF/DOCX controls;
- audit evidence;
- historical estimate/SOW configuration, template and composition reproducibility.

Smoke scenarios are also marked `release` so the broader gate is cumulative. A red P0 smoke gate is intentionally resolved before relying on the broader release run; release-only tests remain implemented but are not treated as passing until separately executed.

## Failure evidence and flakiness policy

Retries are zero locally and in CI. A first-fail/second-pass behavior is considered flakiness to investigate, not a reason to add automatic retries.

JUnit XML reports are retained on successful and failed runs. On browser failure the workflow also retains:

- Playwright trace;
- failure screenshot;
- pytest output;
- FastAPI application log.

Video is intentionally disabled in Phase 1 unless later evidence shows that it materially improves diagnosis.

## Commands

Normal deterministic testing needs no browser download or launch:

```bash
pytest
```

After installing `requirements-e2e.txt`, installing Chromium, migrating an isolated database and starting the local app:

```bash
pytest tests/e2e
pytest tests/e2e -m smoke
pytest tests/e2e -m release
```

## Golden Scenario strategy

The Phase 1 matrix contains 12 MEP and 12 CIP scenarios spanning representative Net New, Install Base, Small Project, EPP, platform move, application/package/components, UAT, delivery markup, Desktop/Mobile/custom/report/label/Boomi/REST, testing modifiers and internal non-billable treatment.

These are deterministic domain tests, not 24 browser journeys. The expected-results file is immutable test-oracle input during execution; application output is compared to it, never used to populate it. A mismatch is classified as one of:

- implementation defect;
- obsolete test;
- specification conflict;
- unresolved business-rule decision.

The matrix does not override a more explicit approved invariant. The approved Investment funding clarification supersedes the conflicting v0.3.25.1 non-billable wording for CIP-1.0.2. Historical engines retain their prior semantics; their Golden expectations are not rewritten to match new behavior.

## CI release gate

The existing `Application Tests` workflow remains authoritative and separate. Browser Tests provision PostgreSQL 18, run Alembic, install Chromium, start `uvicorn app.run:app`, wait for `/health`, seed synthetic users, run smoke/release and upload failure artifacts. The Production Render architecture and normal deployment runtime remain untouched.

A deployment is not considered functionally clean merely because deterministic tests are green. Release-critical browser failures and specification conflicts must be reviewed as part of deployment validation.

## Phase 1 remediation and execution evidence

The original smoke run exposed the CIP funding specification conflict and MEP Save Detail persistence defect. The user approved the funding interpretation in [Investment funding clarification](INVESTMENT_FUNDING_CLARIFICATION.md); CIP-1.0.2 implements it and the Explain assertion now checks that rule.

MEP Save Detail and Save Calculations now explicitly flush pending adjustments before recalculation. `SessionLocal` disables autoflush, so new rows were previously absent from the calculation query even though the later commit saved them. Four integration cases cover new/existing rows on both routes, inspecting persisted hours, fees, ranges and duration immediately after POST, before any GET could repair the summary. The unchanged browser scenario remains the independent 163.5 hours / $40,875 oracle.

Fresh verification results are recorded in `PHASE1_VERIFICATION.md` and PR #66. Do not infer passing release coverage from the presence of tests.

## Intentional Phase 1 exclusions

Browser automation does not duplicate every formula, Golden scenario, migration or document XML assertion. Cross-browser certification, AI-based test selection, pixel comparison, load/performance testing and Production synthetic monitoring are outside Phase 1. Chromium expansion should occur only after the functional suite is stable and cross-browser certification has a business requirement.

## Ongoing change control

Every new feature, approved calculation rule, or defect fix must update the requirements-to-test matrix and add or update the appropriate deterministic, Golden, integration or browser scenario. Record the source of changed expectations. Run the matching release gates against the final commit before calling a deployment validated. A green test run alone does not configure Render deployment blocking or GitHub branch protection.

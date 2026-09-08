# Playwright E2E Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight Python Playwright/pytest browser-testing layer and a controlled 24-scenario domain Golden matrix without changing Estimator business behavior or production Render architecture.

**Architecture:** Keep the existing deterministic `Application Tests` workflow authoritative and unchanged in purpose. Add a separate browser workflow that provisions PostgreSQL 18 as an ephemeral GitHub Actions service, migrates it with Alembic, starts the checked-out FastAPI app, seeds synthetic users, installs Chromium only, and runs pytest-playwright against localhost. Browser tests use the real HTTP/session/RBAC/workflow stack and may query the same isolated database for authoritative persistence assertions, but never bypass authentication for user actions. Golden scenarios remain deterministic Python/domain tests with static approved expected results.

**Tech Stack:** Python 3.12, pytest 8.4.2, pytest-playwright 0.9.0, Playwright 1.62.0, Chromium, FastAPI/Uvicorn, SQLAlchemy, Alembic, PostgreSQL 18, GitHub Actions.

**Spec:** Cloud Inventory Services Estimator No-Code Reconstruction Specification v0.3.25.1, locked baseline SHA `6f724b7dcce4ae3f798df2e5d0fa661c52a1a171`; user-approved Playwright implementation requirements dated 2026-09-04.

## Global Constraints

- Branch from exact baseline `6f724b7dcce4ae3f798df2e5d0fa661c52a1a171`.
- Do not modify calculation, lifecycle, RBAC, configuration, Schedule/Jira, SOW, audit or historical-reproducibility business behavior.
- Do not add Playwright to `requirements.txt` or Render runtime/deployment configuration.
- Do not add Node/npm project files or require developer-managed Node.js.
- Chromium only in Phase 1.
- No test-only authentication bypass.
- No browser test may target Production; Phase 1 browser host allow-list is localhost/127.0.0.1 only.
- Existing deterministic tests remain independently runnable without browser binaries.
- Browser retries are zero.
- Failure artifacts: trace, screenshot, pytest output, application log.
- CI database is ephemeral PostgreSQL 18; no Render test service/database.
- Static Golden expected values are controlled test data and must not be computed from current application output during test execution.

---

### Task 1: Add structural test-harness contract (RED)

**Files:**
- Create: `tests/test_e2e_harness_contract.py`

**Interfaces:**
- Consumes: repository file layout only.
- Produces: deterministic contract checks that fail until the E2E harness is present.

- [ ] Add tests asserting: separate `requirements-e2e.txt`; pinned Python Playwright packages; no Playwright in production requirements/render; browser workflow uses PostgreSQL 18, Chromium and Uvicorn health wait; no npm/node setup; pytest markers exist; architecture/coverage docs exist; 12–18 E2E test functions exist; localhost production-safety guard exists.
- [ ] Run through hosted Application Tests and confirm expected RED due to missing E2E assets.

### Task 2: Add isolated E2E dependency/config foundation (GREEN)

**Files:**
- Create: `requirements-e2e.txt`
- Modify: `pytest.ini`
- Modify: `conftest.py`
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/support/__init__.py`
- Create: `tests/e2e/support/users.py`
- Create: `tests/e2e/support/flows.py`
- Create: `tests/e2e/support/db.py`

**Interfaces:**
- Produces `app_url`, real `page`, `e2e_users`, login/logout/create helpers, isolated DB inspection/setup helpers.
- E2E collection is skipped for ordinary root `pytest` unless `tests/e2e` is explicitly requested or `E2E_RUN=1`.

- [ ] Pin `pytest-playwright==0.9.0` and `playwright==1.62.0` in `requirements-e2e.txt`, inheriting `requirements-dev.txt`.
- [ ] Register `e2e`, `smoke`, and `release` markers.
- [ ] Extend root collection hook so normal deterministic runs skip E2E without launching browsers; explicit `pytest tests/e2e` still runs.
- [ ] Refuse any E2E base URL whose hostname is not localhost/127.0.0.1.
- [ ] Seed fixed synthetic users for ADMIN, TOOLS_ADMIN, ESTIMATOR, REVIEWER, APPROVER, SOW_APPROVER, READ_ONLY, multi-role and inactive cases using the isolated DB only.

### Task 3: Add 24-scenario controlled Golden domain matrix

**Files:**
- Create: `tests/golden/expected_v03251.json`
- Create: `tests/test_golden_scenarios_v03251.py`

**Interfaces:**
- Static expected JSON is immutable test baseline; test setup mutates synthetic revisions then invokes authoritative domain engines.

- [ ] Add 12 MEP scenarios: default, On Prem, Small Project Install Base, EPP Cloud, EPP On Prem, both platform moves, application, package, component/integration mix, UAT-heavy, optional-services/markup.
- [ ] Add 12 CIP scenarios: default, Install Base, Small Project, EPP Cloud/On Prem, Desktop baseline/mod, Mobile+custom, report+label testing modifiers, Boomi, REST multi-consumer, combined modifiers/nonbillable.
- [ ] Assert static expected hours/fees and CIP nonbillable/internal/testing values where applicable.
- [ ] Document that expected values are frozen from approved v0.3.25.1 rules, not generated by the implementation under test.

### Task 4: Add six Playwright smoke journeys

**Files:**
- Create: `tests/e2e/test_smoke.py`

**Interfaces:**
- Uses accessible role/label/text locators first; stable form names only where current table markup provides no accessible label.

- [ ] Active/inactive authentication.
- [ ] Multi-role union, Read Only mutation denial, Tools Admin navigation boundary.
- [ ] MEP create: YYYYMMNNN, immutable product, config/engine pin.
- [ ] MEP autosave + ERP catalog reset + 0.5 Detail adjustment/notes + Golden result persistence after reload.
- [ ] CIP create/release + 0.25 development/testing adjustment + Plan nonbillable treatment + reload.
- [ ] DRAFT→REVIEW→APPROVED lock, action visibility and server-side locked mutation rejection.

### Task 5: Add ten release-critical Playwright journeys

**Files:**
- Create: `tests/e2e/test_release_governance.py`
- Create: `tests/e2e/test_release_schedule_jira.py`
- Create: `tests/e2e/test_release_sow.py`
- Create: `tests/e2e/test_release_history_outputs.py`

**Interfaces:**
- All tests are marked `release`; smoke tests also carry `release` so `pytest tests/e2e -m release` is a superset.

- [ ] Last-active Administrator UI protection.
- [ ] Revision and Rebase rationale, source immutability and one-working-revision rule.
- [ ] Schedule generation/manual edit/stale warning/stale CSV/no implicit regeneration/explicit regeneration.
- [ ] Jira valid Blocks, self/duplicate/cycle/capacity guards and relationship CSV mapping.
- [ ] Configuration ACTIVE→DRAFT→PENDING_REVIEW→APPROVED→ACTIVE with preparer SoD, reason requirements, same-product retirement and historical estimate pin.
- [ ] MEP Net New SOW complete lifecycle plus approval/rejection controls and audit.
- [ ] MEP Small Project SOW complete lifecycle.
- [ ] CIP Net New and CIP Small Project family-routing/template-pin coverage.
- [ ] Representative PDF/DOCX business-content, DRAFT/approved treatment and Track Changes protection checks.
- [ ] Historical config + SOW template/composition reproducibility after newer versions activate.

### Task 6: Add PostgreSQL-backed browser CI

**Files:**
- Create: `.github/workflows/browser-tests.yml`

**Interfaces:**
- Pull requests run `-m smoke`; push to `main` and manual dispatch run `-m release`.

- [ ] Provision `postgres:18` service with health check.
- [ ] Install `requirements-e2e.txt`; run a focused deterministic prerequisite set.
- [ ] Apply Alembic migrations to PostgreSQL.
- [ ] Install Chromium using `python -m playwright install --with-deps chromium`.
- [ ] Start `uvicorn app.run:app` on localhost and poll `/health`.
- [ ] Seed synthetic E2E users after startup seeding/reconciliation.
- [ ] Run smoke/release suite with `--browser chromium`, `--tracing retain-on-failure`, `--screenshot only-on-failure`, no video/retries.
- [ ] Upload Playwright output and app log on failure.

### Task 7: Add testing architecture and requirements-to-test matrix

**Files:**
- Create: `docs/AUTOMATED_TESTING_ARCHITECTURE.md`
- Create: `docs/AUTOMATED_TEST_COVERAGE.md`

- [ ] Document testing layers, isolated Postgres strategy, synthetic data, commands, CI, Golden strategy, browser philosophy, release gates, evidence and exclusions.
- [ ] Map specification requirements to test IDs/layers/criticality/status/expected result, explicitly including reconstruction specification Section 15 audit requirements and known remaining gaps.

### Task 8: Hosted verification and controlled merge

- [ ] Run deterministic Application Tests on exact PR head; no existing expectations weakened.
- [ ] Run browser smoke workflow on exact PR head with PostgreSQL 18 + Chromium.
- [ ] Review failures as implementation defect / obsolete test / specification conflict / unresolved decision; never change expected values solely to get green.
- [ ] Confirm no `requirements.txt` or `render.yaml` testing dependency/environment change.
- [ ] Merge only exact green head; verify post-merge deterministic tests and browser release workflow.
- [ ] Verify Render auto-deploy, if triggered by the documentation/test-only main commit, remains healthy and application runtime version/behavior is unchanged.

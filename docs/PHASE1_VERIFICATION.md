# Phase 1 verification — PR #66

Remediation starting point: `7b2e513d12a96bd9f7d2ff469a7efecca96b622c`.

## Passing release evidence

Tested application/test/workflow commit: **`40f028e822ac035d7914fecfe46c8704936f00d9`**. Both GitHub Actions jobs passed on 2026-10-01, with no test retries.

| Gate | Result | Test execution time |
|---|---|---|
| [Application Tests 36921422481](https://github.com/campbellhatchard/mep-estimate-app/actions/runs/36921422481) | 167 passed, 2 existing skips; includes all 24 Golden scenarios | 207.98s |
| Focused SOW lifecycle gates | 6 passed, 1 existing skip | 9.11s |
| SOW assumptions | 1 passed | 2.54s |
| [Browser Tests 36921422411](https://github.com/campbellhatchard/mep-estimate-app/actions/runs/36921422411), deterministic prerequisites | 10 passed | 7.05s |
| Chromium smoke | 6 passed | 11.67s |
| Chromium release-only | 10 passed | 69.47s |
| Alembic migrations | SQLite and PostgreSQL 18 passed | Included in jobs |

Approximate job wall times, including setup/cleanup: Application Tests **3m59s**, Browser Tests **2m52s**. Browser deselections reflect smoke/release segmentation, not skipped coverage. The two superseded SOW skips and third-party warning are detailed below. No flaky pass obtained through retries is claimed; earlier navigation races were corrected explicitly.

[Successful browser JUnit reports](https://github.com/campbellhatchard/mep-estimate-app/actions/runs/36921422411/artifacts/11192980084) contain both suites. Earlier failed runs demonstrated trace, screenshot and application-log retention (14-day retention). These artifacts can expire; the committed record and CI logs retain the result summary.

This evidence update changes documentation only. PR #66 records the subsequent final documentation-head CI result so the committed report does not imply a run on an untested SHA. No merge or deployment was performed.

### Deliverables and constraints

49 files differ from the controlled baseline. Main additions are `.github/workflows/browser-tests.yml`, `requirements-e2e.txt`, the `tests/e2e/` harness and 16 journeys, fixed 24-scenario Golden data/tests, funding/persistence/lifecycle regressions, and the architecture/coverage/verification documents. Application changes repair MEP persistence, CIP-1.0.2 funding and revision behavior, and shared form submission; the investigation below explains the defects.

Only E2E dependencies were added: **pytest-playwright 0.9.0** and **playwright 1.62.0**, isolated in `requirements-e2e.txt`. Production/development requirements, Render configuration, permanent database architecture and required Production environment variables are unchanged. There is no Node/npm development requirement. Chromium runs against a real localhost FastAPI process and ephemeral PostgreSQL 18 using synthetic data and normal authentication.

Recommended Phase 2: trace every Golden expectation to an approved source; strengthen audit actor/reason and schedule-regeneration assertions; expand lifecycle/document edge cases; add cross-browser certification only for an identified business requirement. MEP Investment allocation remains outside this remediation. See the requirement-level [coverage matrix](AUTOMATED_TEST_COVERAGE.md) for the actual assertions and gaps.

## Reproduced before correction

New MEP Detail and Calculation adjustment rows saved correctly but left the persisted summary stale. Existing-row update cases passed. The CIP Explain assertion required obsolete wording. Focused reproduction: **3 failed, 2 passed**.

## Local verification

After explicit pre-calculation flushes on both MEP save routes and the approved Explain assertion update: **16 passed** (persistence, Explain, Investment funding, precision, preview controls). Browser smoke assertions are unchanged.

Final local deterministic verification passed. Publication was subsequently approved and CI executed as recorded below. **Do not merge until the final commit passes all required gates.**

The full-release-tests PR label opts this branch into six smoke tests followed by ten release-only journeys in isolated GitHub Actions PostgreSQL 18 / Chromium. No retries are configured.

## Review findings resolved

Independent code review identified additional release blockers in the prior funding implementation: locked CIP-1.0.2 precision dispatch; copied MEP/CIP summaries calculated through captured legacy functions before copied rows are flushed; non-Plan allocation notes missing on reload; and contradictory PM Explain wording. Each finding was reproduced with targeted lifecycle and persistence regressions before correction. No merge or deployment is authorized by a partial passing run.

Review regression reproduction: **9 failed, 2 passed**, confirming all four review findings. Correction: shared precision formulas are called without legacy locked dispatch for CIP-1.0.2; revision-copy bindings use current engines and flush copied rows; non-Plan notes are restored; PM Explain uses gross effort. Rebase testing also reproduced duplicate CIP custom slots; copying custom rows before catalog synchronization removes the duplicate insertion. Focused verification including existing revision-history tests: **18 passed**. Existing revision tests now flush source fixtures and use the current MEP engine so the oracle is authoritative rather than stale.

The initial full deterministic run (before lifecycle hardening) passed **157 tests, 2 skipped** in 195.05 seconds. Alembic validation passed on isolated SQLite. Final results follow below.

## Final local evidence

Application/test/workflow commit: `44d679fda8881944ba09f069928c482bfddb9030`.

Command: `PYTHONPATH=. ../mep-venv/bin/python -m pytest -q -ra --strict-config`.

Result: **167 passed, 2 skipped, 1 warning in 224.77 seconds**. This includes all **24 Golden scenarios (12 MEP + 12 CIP)** and the new persistence/lifecycle regressions. No retries were used. The warning is the third-party Starlette TestClient use of the deprecated AnyIO BlockingPortal alias.

The two existing skips are the superseded monolithic SOW lifecycle test in `test_zzz_sow.py` and the superseded SOW approval-lock test in `test_zzzb_sow_approval.py`; focused replacement coverage executed in the full suite.

Alembic `upgrade head` passed on a separate local SQLite database. `git diff --check` passed. No changes were made to `render.yaml`, production requirements, development requirements or E2E dependency pins during this remediation; no Node project, Render service, permanent database, or production environment variable was added.

## Publication and environment

The initial publication was blocked by automatic approval review. The user subsequently explicitly approved publishing to this repository and branch, and the connected GitHub app published the identical local Git tree. That approval block is resolved. Local Chromium installation was unavailable; all browser evidence below comes from isolated GitHub Actions PostgreSQL 18 / Chromium, with normal authentication and synthetic localhost data.

No merge or deployment has occurred. Render deployment gating/branch protection has not been changed.

## Remaining scope

CIP-1.0.2 supports the approved funding allocation. MEP funding allocation is not yet implemented; MEP changes here address calculation persistence and version-correct revision copying. Golden provenance hardening and additional lifecycle/document edge cases remain Phase 2 work, as described in the coverage matrix.

## First published CI run (2026-10-01)

User approved publication. The connected GitHub app published the identical tree as `e56377d42e53ffb6a7f9ca2f97675006b69a5a0d`; prior publication-block notes above are historical. Application Tests run `36919728468` passed: 167 regression tests, 2 skips, 24 Golden cases included; focused SOW gates 6 passed/1 skipped; assumptions gate 1 passed. Browser run `36919728406`: prerequisites 10 passed; smoke **6/6 passed in 10.09s**; release-only **1 passed/9 failed in 110.65s**, zero test retries. Failure artifact `11190729203` retains traces/screenshots/application logs; report artifact `11190749046` retains JUnit.

Trace-based classification:
- Implementation: shared fetch form handler discarded the HTTP 200 revision-rationale HTML by reloading the estimate; revision-entry forms now use native submission.
- Implementation: a hidden input named `action` shadowed `form.action`, causing Jira UI POST to `/estimate/9/[object HTMLInputElement]` (404). The handler now reads the action attribute.
- Implementation: every form was converted to multipart; a full schedule exceeded the parser's 1,000-field limit. The handler now preserves normal URL encoding for ordinary forms and multipart for explicit file uploads, without lifting server limits.
- Test harness: successful fetch-backed POST clicks returned before navigation, leaving stale URL/state reads; release helpers now wait for navigation, not sleeps or retries. Configuration confirmations are accepted explicitly, and Small Project uses the actual `Create Small Project SOW` control. All business assertions remain.

Focused deterministic verification of the form/rationale/Jira/harness changes: **18 passed**. A new CI run is required before accepting these changes as browser-verified.

## Second CI run and final test corrections

At `ab063fd59460db2b61f9a34c9b03bab7aabc6209`, Browser Tests run `36920689467` passed all **6 smoke tests in 10.50s** and **9 of 10 release-only tests in 66.54s**. The sole release failure was fixture insertion using a deprecated `datetime.utcnow` model default under Python 3.12 warnings-as-errors. The historical-pinning fixture now supplies explicit `utc_now()` creation timestamps; runtime warning filters and business assertions are unchanged.

Application Tests run `36920688973` found one stale static assertion expecting `form.action`; it now checks the safe `getAttribute('action')` expression while retaining submitter override checks. Focused routing/harness verification passed **7/7 in 2.34s**. These two test corrections were published as `40f028e822ac035d7914fecfe46c8704936f00d9`.

No test retries were used in any run. Failures were investigated and corrected in new commits; no unchanged-code rerun was used to obtain a pass.

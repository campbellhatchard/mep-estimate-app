# Phase 1 verification — PR #66

Remediation starting point: `7b2e513d12a96bd9f7d2ff469a7efecca96b622c`.

## Reproduced before correction

New MEP Detail and Calculation adjustment rows saved correctly but left the persisted summary stale. Existing-row update cases passed. The CIP Explain assertion required obsolete wording. Focused reproduction: **3 failed, 2 passed**.

## Local verification

After explicit pre-calculation flushes on both MEP save routes and the approved Explain assertion update: **16 passed** (persistence, Explain, Investment funding, precision, preview controls). Browser smoke assertions are unchanged.

Final local deterministic verification passed; GitHub Actions/browser verification is blocked pending push approval. **Do not merge until the final commit passes all required gates.**

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

## Outstanding gate and approval block

Neither push completed. Automatic approval review rejected publication of the modified source/documentation to the public repository, even after the remote was verified as `https://github.com/campbellhatchard/mep-estimate-app.git`, the PR head as `feature/playwright-e2e-phase1`, and connected push permission was confirmed. Explicit user approval of this payload/destination is required before another push attempt. No alternate publishing path was attempted.

PR #66 remains on `7b2e513d12a96bd9f7d2ff469a7efecca96b622c` and unmerged. The `full-release-tests` label was added successfully, but the new workflow has not been published. No new GitHub Actions run or PostgreSQL/Chromium success is claimed. Local browser installation also failed due runtime dependency restrictions and an invalid browser download; this is not browser test evidence.

After approval: push this commit and its documentation follow-up to the existing PR branch, execute the six unchanged smoke journeys, then the ten release-only journeys, investigate any failures, and update this record and the PR description with final commit-specific CI evidence. Do not merge while these gates are unverified. Render deployment gating/branch protection has not been changed.

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

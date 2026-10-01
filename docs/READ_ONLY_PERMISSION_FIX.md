# Read Only permission correction

## Objective and evidence

Fix DEF-RO-001 and DEF-RO-002 from the October 1 interactive regression. Read Only users could edit estimate and SOW fields locally and were offered actions that server authorization rejected. Browser observations established the misleading UI; they did not demonstrate successful unauthorized saves.

Code tracing found lifecycle-only `readonly` values on MEP/CIP estimate, detail, calculation and SOW contexts. Schedule and lifecycle templates also tested status without role. The existing mutation endpoints already enforce authoring roles. A separate integration reproduction confirmed an adjacent persisted side effect: non-author Schedule/Jira reads could generate initial schedule rows.

## Design

`app/permissions.py` owns the existing authoring role sets and the role/state predicates used by page contexts. The estimate mutation guards import the shared role set. SOW mutation routes retain `PREP_ROLES` as a compatibility alias to the shared SOW role set.

- Estimate entry, detail and calculation fields: an authoring role **and** Draft/Review state.
- Schedule inputs, Save and Regenerate: an authoring role **and** Draft state, preserving the existing UI lifecycle rule.
- SOW authoring fields and repeatable rows: a preparation role **and** Draft SOW state, across MEP/CIP New Client and Small Project families.
- New Estimate, draft submission, revision/rebase and historical revision creation: require the existing authoring grant in addition to existing state checks.
- Eligible Small Project SOW creation: require the preparation grant; eligibility alone does not grant access.
- Initial schedule generation through Schedule/Jira reads: only estimate authors can trigger it. Non-authors see an explanatory empty state; Jira export returns 409 until a schedule exists. Persisted schedule viewing and exports remain available.

The existing any-role behavior is intentional. READ_ONLY plus ESTIMATOR still grants authoring permission. READ_ONLY, TOOLS_ADMIN or SOW_APPROVER alone does not. SOW approval assignment, segregation of duties and protected lifecycle transitions retain their separate rules.

Server checks remain mandatory. Disabled fields and absent buttons improve the interface; they are not the security boundary. Existing field flags also prevent estimate autosave scripts from being rendered for non-authors.

## Alternatives and risk

Hiding controls with JavaScript would be a smaller patch, but would leave editable server-rendered HTML and duplicate permission rules in the browser. A role-name blacklist would incorrectly disable mixed-role users. Replacing the authorization framework would introduce substantially more risk than this correction needs.

The main regression risk is suppressing legitimate author actions or enabling locked records. Literal role/state test expectations cover both sides. Existing calculation formulas, commercial data, stored SOW wording, approval rules and deployment infrastructure are outside this change.

The schedule change resolves the specific initial-generation side effect reproduced by tests. It does not establish that every application GET is free of all persistence effects; that broader audit remains part of the incomplete regression.

## Verification and traceability

| Defect / affected checks | Automated guard |
|---|---|
| DEF-RO-001; RO-006/008/041 | MEP/CIP entry/detail/calculation role and state matrix |
| DEF-RO-001; RO-042 | Schedule role/state matrix and forged save/regenerate denial |
| DEF-RO-001; RO-043 | Approved/Final and historical revision controls |
| DEF-RO-002; RO-040 | All four draft SOW families across eight role combinations; locked-state checks |
| Related Small Project creation | Missing-SOW creation action hidden for three non-author profiles, both products |
| RO-015 initial-generation uncertainty | Non-author Schedule/Jira requests leave schedule row count zero |
| Permission preservation | Mixed Read Only/Estimator save; existing-schedule export permitted without replacing rows |
| Browser runtime behavior | Six Chromium cases in `tests/e2e/test_readonly_permissions.py`, included in smoke/release markers |

The first integration run reproduced 51 failures and 97 passes. The initial correction passed those 148 tests. Six additional empty-SOW tests then reproduced the missing creation-button guard before its correction. The final expanded integration module contains 156 cases.

The browser cases use the existing isolated-localhost test harness and synthetic users. They create records, switch profiles, navigate forms, reload, inspect disabled/absent controls and verify authoring still works. API/integration results are not relabeled as interactive production UAT.

Production defects remain **implemented, awaiting deployment and interactive retest** until the corrected version is deployed and the affected live paths pass. Full regression remains incomplete; the original blocked exports, responsive checks, lifecycle combinations, field completeness and fresh-session checks are retained.

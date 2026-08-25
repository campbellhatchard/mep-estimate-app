# Build and Release Gates

**Applies to:** Cloud Inventory Services Estimator  
**Current production release:** v0.3.14.1  
**Deployment branch:** `main`

This document defines the minimum engineering controls for changing and releasing the application. Passing CI is necessary but does not by itself constitute business acceptance.

## 1. Development baseline

Every new feature, hotfix or chore must start from current `main` unless an explicitly approved maintenance branch is required for a historical release.

Do not use an old feature branch as the base for new production work simply because it contains earlier code for the same capability.

Accepted baseline branches are historical checkpoints. They are not alternate development trunks.

## 2. Branch and PR discipline

Use one focused branch for one coherent change.

Recommended naming:

- `feature/<release-or-capability>`
- `hotfix/<release-or-defect>`
- `chore/<maintenance-task>`

A PR should not combine unrelated calculation, UI, SOW, migration and infrastructure changes unless they are inseparable parts of one approved release requirement.

Before merge:

1. base branch is current `main`;
2. branch has no unintended old-feature carryover;
3. changed files match the stated scope;
4. migration chain is valid;
5. Application Tests are green;
6. business acceptance criteria for the release are satisfied;
7. deployment-sensitive environment variables are documented but never committed with secret values.

## 3. Main branch protection

GitHub repository settings should enforce:

- pull request required before merge;
- required successful `Application Tests` status check;
- no force pushes to `main`;
- no direct feature development on `main`.

This is a repository setting, not an application-code control.

## 4. Dependency/build validation

GitHub Actions installs `requirements-dev.txt`, which includes the production dependencies required by the application plus test dependencies.

The supported CI Python line is Python 3.12.

A dependency change must be deliberate and must not silently alter calculation or document-generation behavior.

## 5. Migration gate

Every CI run must validate the complete Alembic chain from an empty database:

```bash
rm -f /tmp/mep_estimate_migration.db
DATABASE_URL=sqlite:////tmp/mep_estimate_migration.db PYTHONPATH=. alembic upgrade head
```

For a release that introduces a migration, also validate:

- the new migration's `down_revision` points to the current production migration head;
- no obsolete/abandoned branch migration ID is reused;
- production upgrade behavior is understood;
- downgrade/re-upgrade is tested when feasible and safe;
- foreign keys, uniqueness, indexes and cascade behavior match the domain controls.

## 6. Automated regression gate

The main regression suite is:

```bash
PYTHONPATH=. pytest -q --ignore=tests/test_zzz_sow.py
```

The original monolithic SOW lifecycle scenario in `tests/test_zzz_sow.py` is intentionally retained as historical design/regression documentation but is marked skipped by `tests/conftest.py`. It must therefore **not** be presented by CI as though that exact test executed successfully.

The explicit SOW lifecycle release gate must execute the focused SOW regression modules that replaced the monolithic scenario:

```bash
PYTHONPATH=. pytest -q \
  tests/test_zzza_sow_queue.py \
  tests/test_zzzb_sow_approval.py \
  tests/test_zzzc_sow_lock.py \
  tests/test_zzzz_cip_sow.py
```

The assumptions-to-SOW regression remains explicitly executable:

```bash
PYTHONPATH=. pytest -q \
  tests/test_zzz_sow.py::test_estimate_assumptions_feed_sow_section_414
```

At the v0.3.14.1 validation point, the general regression group reported 60 passing tests and one intentional skip. Future releases should not treat that count as fixed; the relevant gate is that all intended tests pass and skips are understood.

## 7. Calculation regression requirements

Any change touching calculations, inputs, configuration lookup or live preview must prove that UI preview, persisted results and exports remain aligned to the same backend source of truth.

### MEP

- editable/new revisions use engine 1.0.1;
- locked historical revisions must retain historical calculation behavior;
- fractional manual adjustments must not be rounded away;
- calculation totals and displayed precision must remain consistent with the accepted engine.

### CIP

- editable/new revisions use engine CIP-1.0.1;
- locked historical revisions must retain historical CIP behavior;
- MEP/CIP configuration and calculation dispatch must remain isolated.

Changes to calculation semantics require explicit business acceptance, not only green tests.

## 8. Estimate workflow regression requirements

A release that touches shared routes, templates, forms or authorization should validate at minimum:

- authentication and role access;
- estimate creation;
- Draft editing;
- lifecycle transitions;
- revision/rebase behavior;
- Draft estimate deletion eligibility;
- live detail/calculation preview;
- PDF/Jira outputs where relevant;
- error-modal form routing, including controls using `formaction`/`formmethod`.

## 9. SOW regression requirements

For current Net New production behavior, validate both MEP and CIP:

- eligible estimate can prepare SOW;
- save/finalize/send for approval;
- assigned approval queue;
- no self-approval;
- mandatory rejection reason;
- rejected SOW remains immutable and supports new revision;
- approval locks canonical wording and records content hash/snapshot;
- review PDF behavior;
- controlled Word generation in non-approved and approved states;
- historical template version pinning;
- approved Word content verification.

### Controlled Word acceptance

For non-approved SOWs:

- document opens as valid `.docx`;
- DRAFT watermark is present;
- expected header/footer/page presentation exists;
- Track Changes is enabled and password-enforced;
- generated baseline contains no unintended pre-existing revisions;
- source/pinned content is not mutated by generating the export.

For approved SOWs:

- approval hash/snapshot verification succeeds before release;
- approved presentation rules are preserved;
- controlled Track Changes policy remains enforced as defined by the accepted v0.3.14.1 release.

## 10. Small Project release gates

Small Project SOW must be introduced incrementally.

### Foundation gate

Before authoring/workflow is merged:

- MEP Small Project and CIP Small Project template families are independently registered;
- real binary DOCX assets are committed/loaded without fragmented Base64 text packaging;
- asset SHA-256 matches the accepted source document;
- template validation fails closed for corrupt or invalid assets;
- four-family template administration preserves existing Net New families;
- migration upgrades cleanly;
- existing Net New regression remains green.

### Authoring gate

Before Small Project authoring is accepted:

- eligibility is based on approved Small Project estimates for existing implementations;
- MEP/CIP deliverables and conditional methodology follow approved requirements;
- Hypercare is estimate-driven and reconciles to approved hours;
- commercial values reconcile to the approved estimate;
- exact approved weekend/holiday wording is preserved;
- Appendix A conditionality works;
- existing shared SOW lifecycle is reused rather than independently reimplemented.

### Four-family gate

Before production release, run an explicit matrix for:

- MEP Net New
- CIP Net New
- MEP Small Project
- CIP Small Project

including routing isolation, approval, rejection/revision, PDF and controlled Word behavior.

## 11. Document/template asset controls

Controlled commercial source documents are source-of-truth assets and must not be silently modified during packaging.

Required controls:

- store real binary source assets where technically possible;
- record/verify expected SHA-256;
- fail closed when an expected controlled asset is missing or corrupt;
- never silently fall back to a different SOW family/template;
- keep generated outputs separate from stored source templates;
- preserve historical template version pinning.

The repository is currently public. Do not commit proprietary or sensitive controlled templates until public visibility is explicitly confirmed as acceptable or the repository is made private.

## 12. Warning/technical-debt policy

Deprecation warnings are not currently release blockers unless they indicate behavior that will fail in the deployed dependency versions.

Known warning debt should be addressed in a dedicated technical-hardening release rather than mixed into functional releases, unless a specific warning directly blocks the requested feature.

Tracked categories include FastAPI startup events, timezone-naive UTC calls, Starlette template signatures and SQLAlchemy identity-map replacement warnings.

## 13. PR review gate

Before merge, review the PR as a controlled change set:

- scope matches issue/requirements;
- no obsolete branch code was copied wholesale;
- no unrelated files changed;
- no secrets or credentials were introduced;
- no demo/sample legal/commercial content leaked into production templates;
- no migration collision exists;
- no route-registration regression is introduced;
- no historical locked calculation/document behavior is inadvertently changed.

## 14. Merge and release

After approval and green CI:

1. merge the PR into `main` using the repository's approved merge method;
2. allow Render's `main` auto-deploy to start;
3. verify pre-deploy Alembic migration success;
4. verify service health at `/health`;
5. perform representative functional smoke tests;
6. for document releases, generate representative MEP/CIP PDF and Word outputs;
7. record/retain an accepted baseline branch where appropriate.

Do not claim a release is deployed solely because GitHub merged successfully.

## 15. Render production contract

Current `render.yaml` specifies:

- runtime: Python
- plan: Starter web service
- region: Ohio
- branch: `main`
- auto-deploy: commit
- build: `pip install -r requirements.txt`
- pre-deploy: `alembic upgrade head`
- start: `uvicorn app.run:app --host 0.0.0.0 --port $PORT`
- health: `/health`
- PostgreSQL database in Ohio
- `ENVIRONMENT=production`
- `APP_TIMEZONE=America/Chicago`

Required secret values are environment-managed, including `ADMIN_PASSWORD` and `SOW_TRACK_CHANGES_PASSWORD`.

## 16. Acceptance hierarchy

A release is considered accepted only when all applicable levels are satisfied:

1. code/build succeeds;
2. migrations succeed;
3. automated regression passes;
4. feature-specific acceptance tests pass;
5. deployed service is healthy;
6. representative user workflow is functionally verified;
7. the release is explicitly accepted as the new baseline where required.

A green CI run alone is not production acceptance.

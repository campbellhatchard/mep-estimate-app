# Build Validation — Current Production Line

**Current accepted release:** v0.3.14.1  
**Current development base:** `main`

This file is a concise validation status summary. The authoritative release procedure is [`BUILD_AND_RELEASE_GATES.md`](BUILD_AND_RELEASE_GATES.md).

## Current validated capability

The accepted production line includes:

- MEP and CIP estimating;
- configuration and revision pinning;
- corrected MEP engine 1.0.1 and CIP engine CIP-1.0.1 for editable/new revisions;
- historical calculation preservation for locked older revisions;
- estimate lifecycle/revision controls;
- Draft estimate deletion controls;
- live calculation/detail preview;
- schedules, PDF and Jira CSV outputs;
- estimate assumptions;
- MEP Net New and CIP Net New SOW preparation;
- SOW assignment, approval, rejection and revision lifecycle;
- SOW review PDF Draft watermarking;
- controlled Word generation in every SOW state;
- non-approved Word Draft watermarking;
- password-enforced Track Changes;
- approved-content hash/snapshot verification;
- Word header/footer and TOC/page reconciliation.

Small Project SOW authoring is not part of the current production baseline.

## Latest observed automated validation

The v0.3.14.1 production-line regression run completed successfully. The primary regression group reported:

- **60 passed**
- **1 skipped**

The skip is intentional: the original monolithic SOW lifecycle test is retained as historical design/regression documentation and is superseded by focused SOW lifecycle tests.

The GitHub Actions workflow must execute the focused lifecycle modules explicitly rather than presenting the intentionally skipped monolithic scenario as a successful release-gate test.

## Migration validation

CI validates `alembic upgrade head` against a new empty SQLite database before running application regression tests.

Any release adding schema must additionally validate its migration against the current production migration head and must not reuse migration identifiers from abandoned branches.

## Current open release/governance work

Tracked GitHub issues now include:

- #22 v0.3.15 Small Project SOW Foundation
- #23 Small Project SOW Authoring and Workflow
- #24 Four-Family SOW Regression Matrix
- #25 Application Architecture Consolidation
- #26 CI and Deprecation Warning Cleanup
- #27 Configuration Approval Governance
- #28 CRM, Enterprise SSO and Integration Backlog
- #29 Repository Governance and Current Design Specification

## Repository controls still requiring GitHub settings

The repository is currently public and `main` has not been protected through required PR/status-check enforcement.

Before proprietary controlled template assets are committed, confirm whether public visibility is intentional. `main` should also be protected so normal releases require a PR and successful Application Tests.

## Release acceptance

A green CI run is necessary but is not sufficient to declare a release production-accepted. Applicable migration, regression, document-generation, deployed health and representative user workflow checks must also succeed, followed by explicit acceptance of the release baseline.

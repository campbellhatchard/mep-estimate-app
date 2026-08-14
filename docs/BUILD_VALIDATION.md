# Build Validation — v0.1

## Automated validation

Current automated suite: **6 passing tests**.

Validated behaviors:

- health endpoint and application startup;
- case-insensitive username authentication;
- estimate creation and recalculation;
- workbook-style Estimate, Estimate Detail, Calculations, Schedule, Audit, Calculation Data, and User Administration pages render;
- approved workbook cached default baseline reproduces **2 hours / $500 at $250/hour**;
- invalid estimate/go-live combinations are rejected;
- non-zero calculation adjustments require a reason and create audit events;
- configuration versions are immutable for existing estimate revisions;
- explicit rebase creates a new revision pinned to the current Active configuration;
- Approved revisions reject further editing;
- PDF export produces a valid PDF stream;
- Jira CSV export uses the approved workbook's complete **27-column header structure**;
- required calculation parameters have no source-code fallback: if configuration is missing, calculation fails explicitly;
- initial Alembic migration upgrades an empty database successfully.

## Production release gates still open

This build is a runnable application baseline, not a Production parity sign-off. Before Production release:

1. Business-approve the Rule Resolution Register.
2. Execute the Golden Scenario matrix in `PARITY_AND_RELEASE_GATE.md` against the approved workbook/intended results.
3. Resolve every unexplained mismatch.
4. Complete user-acceptance review of workbook-layout fidelity and terminology.
5. Validate the Jira dependency/link mapping required by the delivery team.
6. Apply final production security/identity decisions (local auth vs enterprise SSO) and operational backup/restore testing.
7. Validate final branded PDF content before customer use.

## Known deliberately deferred capabilities

- two-person configuration reviewer/approver enforcement;
- CRM API integration;
- SOW template generation;
- enterprise SSO;
- historical estimate import;
- live project management after estimate generation.

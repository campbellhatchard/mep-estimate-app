# Historical Design Specification — Superseded

This file originally described the initial MEP-only workbook replacement design, including calculation engine 1.0.0 and an architecture in which CIP and SOW generation were future capabilities.

That specification is **no longer authoritative for the current application**.

Use these documents for current development and release decisions:

1. [`CURRENT_SYSTEM_DESIGN.md`](CURRENT_SYSTEM_DESIGN.md) — authoritative current architecture and functional controls.
2. [`BUILD_AND_RELEASE_GATES.md`](BUILD_AND_RELEASE_GATES.md) — authoritative build, migration, regression, PR and release controls.
3. Current accepted code and automated tests on `main`.

The original content remains available in Git history for workbook-era traceability and should be consulted only when investigating the initial design rationale or historical calculation behavior.

## Historical context

The superseded design was based on:

- the approved `Estimate_2026_MEP_18` workbook;
- initial configuration `MEP Estimate Model 2026.08.1`;
- MEP calculation engine 1.0.0;
- MEP-only production scope;
- SOW generation and CIP as future architecture.

Since then the production application has added CIP estimating, corrected/pinned calculation engines, revision lifecycle enhancements, estimate assumptions, MEP and CIP Net New SOW workflows, SOW approvals, controlled PDF review and controlled Microsoft Word generation. Those later accepted capabilities are defined in the current-system documentation rather than this historical file.

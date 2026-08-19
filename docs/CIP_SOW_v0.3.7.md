# v0.3.7 — CIP New Client SOW

This enhancement layers the CIP New Client Statement of Work onto the accepted v0.3.6 MEP SOW baseline without changing the MEP SOW workflow.

## Locked business rules

- Eligible only for Approved/Final/Superseded historical revisions of **CIP + Net New + CIP Install**.
- CIP is always Cloud Inventory hosted; the SOW does not offer a deployment choice.
- Limited Load Test wording is included only when the approved CIP calculation contains non-zero `TEST_LIMITED_LOAD` investment hours. Net New CIP currently calculates zero, so the section is removed.
- CIP Product Version is controlled through Calculation Data category **CIP SOW Setting**, key **Current Version**, and is pinned when the SOW is first created.
- `Deployed Over` drives Appendix A ERP/System behavior: Standalone suppresses ERP detail rows; JD Edwards requires Base Code and Tools Release; other systems retain applicable general fields.
- Barcode Printer Count remains SOW-specific.

## Reused controls

The MEP lifecycle and controls remain authoritative: Draft → Finalized → Pending Approval → Approved/Rejected, distinct SOW Approver role, no self-approval, rejection creates a new immutable SOW revision, template version pinning, PDF approval review, Word download only after approval, and approved-content hash validation.

## Template approach

The controlled CIP content is reconstructed from the source-derived CIP template specification using the accepted active MEP controlled template for the house presentation layer (branding, headers/footers, numbering, TOC and table styling). This preserves the CIP source wording/structure while keeping MEP and CIP SOW presentation consistent.

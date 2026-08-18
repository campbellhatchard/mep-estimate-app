# CIP Rule Resolution Register — v0.3.0

| ID | Workbook condition / defect | v0.3.0 rule |
|---|---|---|
| CIP-RR-001 | Custom Desktop Very Complex contains `#REF!` | Use approved Data value: Very Complex = 80 development hours. |
| CIP-RR-002 | Build module settings checks Customer Type `Add On`, which is not valid | Treat `Add On` as **Install Base**. Install Base = 0 hours; otherwise 24 hours. |
| CIP-RR-003 | UAT Prep checks Deployed Over for `Small Project` | Use **Project Type = Small Project**. |
| CIP-RR-004 | Several LEFT/MID tests cannot match `Install_Base` | Use direct **Customer Type = Install Base** conditions. |
| CIP-RR-005 | Label 1 description uses `>1` while effort uses `>0` | Label 1 exists and receives effort when label count is at least 1. |
| CIP-RR-006 | Integration lookup is hardwired to Release 25.2 although later releases exist | Copy the current approved integration catalog/effort to 25.3/26.1/26.2. New releases clone the latest catalog and can be edited before activation. |
| CIP-RR-007 | Instruction sheets conflict with active estimator formulas | Estimate, Estimate Detail, Calculations and Data are authoritative. Instructions are secondary. |
| CIP-RR-008 | Jira template labels original estimate in seconds | Export Jira original/remaining estimate in **hours**. |
| CIP-RR-009 | Application names contain sprint/date annotations | Strip date/sprint suffixes from user-facing application names; retain release metadata separately when needed. |
| CIP-RR-010 | `NextWorld`, `Stand Alone`, `Oracle Net Suite`, `OKTA` naming | Display Nextworld, Standalone, NetSuite, Okta. |
| CIP-RR-011 | Desktop baseline small-change factor differs from Mobile by 10x | Retain intentionally: Desktop 0.50; Mobile 0.05. |
| CIP-RR-012 | SSO Data values differ but calculation uses flat 16 hours | Retain intentional 16 hours for any non-None SSO method. |
| CIP-RR-013 | EPP Print Bridge can produce a negative value when no additional sites exist | Bound additional sites at zero: `max(0, sites - 1)`. |
| CIP-RR-014 | Design initial test script formula references `V47` among Build column C references | Resolve to the intended Custom Desktop Build scope line (equivalent to Build row C47). |
| CIP-RR-015 | `Other` branches in base IM/prep factors are unreachable from approved Customer Type values | Preserve effective valid-input behavior: IM = 20%, Prep = 10%. |
| CIP-RR-016 | Investment/Plan Not Billable wording is unclear in workbook formulas | User-defined semantics are authoritative: Investment Hours are customer-billed; Plan Hours Not Billable are internal effort excluded from fees. |
| CIP-RR-017 | Setup catalog appears in Baseline CIP Apps | Setup catalog is not selectable; it is part of fixed `Update Module Settings & Config based on BRD` effort. |
| CIP-RR-018 | Mobile Field Inventory items reference MEP Offline | Retain as deliberate MEP-backed capabilities inside a CIP estimate. |

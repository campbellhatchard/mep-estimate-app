# Workbook Rule Resolution Register

This register records places where the approved workbook cannot be transcribed literally without reproducing an error, broken reference, or ambiguous spreadsheet behavior. These resolutions are implemented in the current application build but remain part of the Golden Scenario/business approval gate.

| ID | Workbook issue | Application treatment | Status |
|---|---|---|---|
| RR-001 | Defined names `Base_Effort`, `Customer_Type`, `Deploy_Method`, `EndUserTraining`, `Moons_Version`, `ProjectType`, and `UnitTestingFactor` resolve to `#REF!`. | The application uses explicit named configuration/catalog keys and revision fields instead of broken workbook names. | Implemented; business parity verification required |
| RR-002 | Workbook logic depends on display text/string spellings and contains variants/typos. | Stable internal keys drive logic; workbook-aligned labels remain presentation data. | Implemented |
| RR-003 | Unit-testing effort is embedded through workbook references and defaults. | Unit Testing Factor is an auditable configuration value; estimate-level override is stored separately and requires a reason. | Implemented |
| RR-004 | Numerous numeric constants are embedded inside formulas. | Material effort/factor values are configuration records. Missing required calculation configuration now fails explicitly rather than falling back to a hidden code value. | Implemented |
| RR-005 | `Print Bridge` formula can mathematically yield a negative site increment when no additional site exists. | Additional-site quantity is bounded at zero. | Implemented; business confirmation required |
| RR-006 | Internal Solution Design Review is based on modified/custom development scope, not package effort. | Package effort is excluded, matching the workbook's intended referenced scope. | Implemented; Golden Scenario verification required |
| RR-007 | Application Demonstrations calculation references the application/package/custom population. | Package count is included in the demonstration basis. | Implemented; Golden Scenario verification required |
| RR-008 | End-user documentation/training scope uses standard and custom application population. | Baseline package population is included where the workbook's aggregate application count indicates it should be. | Implemented; Golden Scenario verification required |
| RR-009 | Promotion/stage validation derives from adjusted build scope and Base Package Install. | Estimate-level adjustment to Base Package Install is respected in the promotion calculation rather than using an unadjusted copy. | Implemented; Golden Scenario verification required |
| RR-010 | Readiness/production-validation workbook count expression duplicates Baseline Application count in its source references. | The duplicate count is currently retained to preserve approved workbook behavior until business parity testing confirms whether it is intentional. | Retained pending business decision |
| RR-011 | Jira worksheet contains spreadsheet-specific lookup/link formulas. | Jira becomes a generated 27-column CSV. Epic/Parent hierarchy is populated; dependency/link columns are reserved but not yet relationship-mapped. | v1 implemented; relationship mapping pending |
| RR-012 | Schedule contains >1,000 formulas and date-grid spreadsheet mechanics. | Schedule is generated from a normalized task template and named calculation results; editable fields are stored, derived budget/trend/EAC values are calculated. | Implemented; schedule parity verification required |

No item in this register should be silently changed. A Golden Scenario mismatch must be classified as an application defect, approved workbook defect correction, or approved business-rule change before Production release.

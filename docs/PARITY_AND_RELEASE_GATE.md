# Workbook Parity and Release Gate

## Current verified parity

The approved workbook's cached default scenario shows:

- Estimate Hours: 2
- Fees: 500 at a 250 billing rate
- Low Hours: 2
- Low Fees: 500
- High Hours: 2
- High Fees: 575

The application reproduces the default Hours and Fees values and implements the workbook high-range factor as versioned configuration.

This is **not sufficient** to claim full workbook parity.

## Why a formal parity gate is required

The workbook contains broken names, cached formula errors, positional lookup behavior, duplicated references in at least one testing formula, and business constants embedded inside formulas. Reproducing one cached scenario does not prove that every branch of the workbook behaves as intended.

## Golden Scenario set required before Production

Create and business-approve representative scenarios covering at least:

- Oracle JD Edwards E1
- Oracle Fusion
- Oracle EBS
- SAP
- Stand Alone
- MEP Cloud
- MEP On Prem
- EPP-only
- Small Project
- Install Base
- Net New
- upgrades and Android conversion
- each baseline application configuration level
- each package configuration level
- each custom application complexity
- labels
- IoT/service definitions
- ERP integration
- data replication
- each user-count band
- each test percentage and 1/2/3 UAT sites/cycles
- each go-live option and multiple sites
- each security option
- documentation/training options
- each delivery markup.

For every scenario capture:

- input set;
- Estimate Detail section totals;
- Plan total;
- Design total;
- Build total;
- Test total;
- Go Live total;
- total hours;
- fees;
- low/high range;
- expected schedule budget mapping.

Any mismatch must be categorized as:

1. Application defect;
2. Workbook defect intentionally corrected;
3. Approved business-rule change.

No unexplained mismatch should be accepted.

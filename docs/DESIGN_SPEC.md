# MEP Estimate Application — Locked Design Specification

**Baseline:** Approved workbook `Estimate_2026_MEP_18 (1).xlsx`  
**Initial configuration:** `MEP Estimate Model 2026.08.1`  
**Calculation engine:** `1.0.0`

## 1. Objective

Replace the approved Excel estimator with a web application that preserves the familiar Estimate, Estimate Detail, Calculations, and Schedule layouts while introducing controlled calculation configuration, revision history, auditability, permissions, PDF output, and future integration boundaries.

The workbook is the approved source model, but spreadsheet defects are not intentionally reproduced. Intended business behavior is converted into named deterministic rules.

## 2. Locked decisions

- Administrators can change **value factors**, not arbitrary formulas.
- Every material numeric assumption must be configuration rather than a hidden constant.
- Each estimate revision is permanently pinned to the configuration version used to calculate it.
- A user can explicitly rebase an estimate by creating a new revision against the current Active configuration.
- One Administrator can publish configuration in v1; schema supports future reviewer/approver controls.
- Estimate lifecycle is Draft -> Review -> Approved/Final -> Superseded.
- Estimate Detail retains editable Mod Hours and Notes.
- Unit Testing Factor has a configured default and audited estimate-level override requiring a reason.
- Calculations retains Standard Adjust and Adjust Notes. Non-zero adjustments require a note.
- Schedule is generated from the estimate, not a replacement project-management system.
- Editable schedule fields: Resource Assigned, Status, % Complete, Change Order Hours, Hours Used, Comments, Start, End.
- Calculation Data is viewable by every role and editable only by Administrator.
- Administrators may add new ERP/options/catalog data.
- Historically used catalog entries are deactivated rather than deleted.
- Jira worksheet becomes Jira CSV export.
- v1 generates a PDF estimate. Architecture anticipates future template-based SOW generation.
- Layout and terminology remain recognizably aligned with the workbook to reduce adoption friction.
- Roles: Administrator, Estimator, Reviewer, Approver, Read Only.
- Historical Excel estimates are not imported for initial release.
- CRM fields are manually entered in v1; CRM is an API integration boundary later.
- Initial deployment is GitHub -> Render with PostgreSQL.

## 3. Dependency chain

```text
Estimate inputs
   -> Estimate Detail engine
      -> Phase calculation engine
         -> Estimate summary
            -> Generated schedule
               -> PDF / Jira CSV
```

There is one backend calculation source of truth. UI pages and exports cannot implement independent formulas.

## 4. Calculation model

### Inputs
Estimate-specific selections such as ERP, project type, user count, applications, custom complexity, testing, sites, and go-live method.

### Configuration
Versioned business values such as effort hours, percentages, multipliers, dropdown/catalog choices, ERP application catalogs, and schedule statuses.

### Rules
Named source-controlled calculations in `app/services/calculation.py`. Administrators do not edit rules in v1.

### Overrides
Estimate-level changes stored separately from the standard value. They never overwrite the original configured/calculated value.

## 5. Configuration governance

Configuration versions have Draft, Active, and Retired states. Existing revisions never change when a new configuration is activated.

The database contains future workflow fields for submitted/reviewed/approved metadata. v1 allows a single Administrator to create a Draft, change values with a mandatory reason, and activate it.

On rebase:

1. source revision remains immutable;
2. new Draft revision is created;
3. current Active configuration is pinned;
4. current calculation engine version is pinned;
5. existing catalog selections are preserved;
6. newly introduced catalog entries are appended as unselected choices;
7. results are recalculated.

## 6. Estimate page

Preserve workbook visual structure and section ordering:

- Definition and Application Summary
- Baseline Applications
- Baseline Packages
- Custom Applications
- labels/integration/data-rep inputs
- test/go-live inputs
- Optional Services
- Project Delivery
- Summary
- Presales Components

Dropdown values are configuration-driven. ERP determines the application/package catalog. Calculation summary refreshes after save.

## 7. Estimate Detail

Columns:

- Ref
- Definition
- Base Hours
- Mod Hours
- Dev Subtotal
- Unit Testing
- Notes
- Total

Sections:

- Upgrade Definition
- Baseline Applications
- Baseline Packages
- Custom Applications
- Labels
- IoT Service Definitions
- ERP Service Definitions
- Data Replication Sessions

Mod Hours is editable. Any non-zero adjustment requires Notes. Unit Testing Factor override requires a reason. Base/calculated values remain separate from adjustments.

## 8. Calculations

Phases:

- Plan
- Design
- Build
- Test
- Go Live

Columns:

- Description
- Standard Hours
- Standard Adjust
- Standard Extended
- Adjust Notes

Standard Hours is system-calculated. Standard Adjust remains editable. A non-zero adjustment requires an explanation. Calculation rows use immutable internal rule keys and include an Explain trace.

## 9. Schedule

The Schedule uses the workbook's descriptive columns and generated phase/task structure. Initial budgets are mapped from calculation/detail lines.

A schedule is marked stale after estimate/detail/calculation changes. It is **not** silently regenerated because the user may have made deliberate schedule edits. The user must explicitly Regenerate Schedule and is warned that manual schedule changes are replaced.

The UI uses sticky descriptive columns plus a horizontally scrolling date/Gantt area.

## 10. Calculation Data

The workbook Data sheet is normalized into searchable categories instead of being reproduced as a positional spreadsheet.

Representative categories:

- Global Parameters
- Customer Type
- ERP
- Solution Type
- User Count
- Upgrade Type
- Application Effort
- Custom Effort
- Package Effort
- Testing Factors
- Go Live
- Delivery Method
- Security Method
- EPP Install / EPP Integration
- ERP Application
- ERP Package
- Schedule Status
- Currency
- Entity

Every item has an internal key, display label, type/value, optional scope/parent, Active flag, version, and audit history.

## 11. Audit model

Audit events are append-only application records. Covered actions include:

- estimate creation and field changes;
- revision creation/rebase;
- detail adjustments;
- calculation adjustments;
- unit-test-factor override;
- schedule generation/regeneration and schedule field changes;
- configuration version/item changes and activation;
- estimate lifecycle actions;
- PDF and Jira CSV generation.

Audit captures user, timestamp, entity/revision/configuration IDs, field, previous/new value, and reason when applicable.

## 12. Lifecycle and permissions

### Administrator
Full estimate access plus user/configuration administration.

### Estimator
Create/edit Draft estimates, revisions, approved estimate outputs, adjustments, and schedule.

### Reviewer
Review and return estimates; editing capability is currently allowed in the same controlled Draft workflow.

### Approver
Approve and supersede revisions.

### Read Only
View estimates, details, calculations, schedules, configuration, and permitted exports without mutation rights.

Approved/Final/Superseded revisions are locked. Any later change requires a new revision.

## 13. Outputs and integration boundaries

### PDF
Structured estimate PDF built from domain data, not a screenshot. Output service is intentionally reusable for later SOW generation.

### Jira
Generated Schedule is converted to Jira CSV; Jira formatting does not alter schedule domain data.

### CRM
Future adapter will search/read opportunity/customer information and associate external IDs. v1 fields remain manual.

## 14. Persistence and deployment

- FastAPI application.
- SQLAlchemy domain layer.
- PostgreSQL production database.
- SQLite local-development fallback.
- Alembic migrations.
- GitHub-hosted source.
- Render web service and Render PostgreSQL via Blueprint.
- Environment secrets for session key and initial Administrator password.

## 15. Workbook defects and rule resolution

Known broken workbook named ranges include Base_Effort, Customer_Type, Deploy_Method, EndUserTraining, Moons_Version, ProjectType, and UnitTestingFactor.

The implementation therefore retains the extracted original formulas and source inventory under `docs/`. Any disputed formula must be resolved as a business-rule decision rather than silently inferred.

## 16. Production release gate

Production approval requires:

1. rule catalog review;
2. configuration inventory review;
3. known workbook-defect disposition;
4. 20–30 Golden Scenario parity tests spanning ERPs/project types/options;
5. automated unit/regression tests;
6. user acceptance review of page layout and terminology;
7. PDF/Jira output validation;
8. staging deployment before Production.

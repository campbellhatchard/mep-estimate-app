# Schedule CSV and Jira Export Parity — v0.3.20

## Purpose

This register documents the export contract used by the MEP and CIP Estimator schedules. It is based on the original approved Estimate workbook/template behavior, the retained Schedule source inventory, and the existing CIP rule-resolution register.

The two exports serve different purposes:

- **Schedule CSV** is the operational project-schedule export. It reflects the currently persisted Schedule, including user edits and workbook-derived budget/health metrics.
- **Jira CSV** is a Jira-import compatibility artifact. It preserves the approved 27-column workbook-style schema and maps only data that can be sourced deterministically from the Estimate/Schedule domain.

Neither export is permitted to fabricate Jira account identities, Jira issue relationships, or external IDs.

## Schedule CSV contract

Schedule CSV reads `ScheduleTask` rows already persisted for the Estimate revision. It does **not** regenerate the Schedule, including when `schedule_needs_refresh` is true. If no Schedule exists, the route returns HTTP 409 and directs the user to generate/open the Schedule first.

| CSV field | Source / calculation |
|---|---|
| Task ID | `ScheduleTask.task_id` |
| Phase | `ScheduleTask.phase` |
| Task | `ScheduleTask.task` |
| Task Owner / Persona | `ScheduleTask.task_owner` |
| Description | `ScheduleTask.description` |
| Purpose / Goal | `ScheduleTask.purpose` |
| Resource Assigned | persisted `ScheduleTask.resource_assigned` |
| Status | persisted `ScheduleTask.status` |
| Percent Complete | persisted percent; phase rows use workbook-equivalent weighted roll-up |
| Non-Billable Hours | persisted non-billable hours; phase rows roll up child tasks |
| Billable Hours Budgeted | persisted estimate-derived billable budget; phase rows roll up child tasks |
| Change Order Hours | persisted user-entered change-order hours; phase rows roll up child tasks |
| Hours Used | persisted user-entered actual hours; phase rows roll up child tasks |
| Billable Hours Remaining | workbook-equivalent derived remaining value from Schedule metrics |
| Budget Trend / Health | workbook-equivalent `On Track`, `Trending Under`, `Trending Over`, or `Over Budget` |
| Estimate at Completion | workbook-equivalent derived EAC |
| Comments | persisted `ScheduleTask.comments` |
| Start Date | persisted/generated start date; phase rows derive min child start |
| End Date | persisted/generated end date; phase rows derive max child end |

An audit event `SCHEDULE_CSV_EXPORTED` records the acting user, Estimate and revision. When a stale Schedule is exported, the event reason explicitly records that the persisted stale Schedule was exported without regeneration.

## Jira 27-column compatibility contract

The original workbook Jira template is preserved as a 27-column structure. The application does not add Schedule-only operational columns to this file because doing so would change the Jira import contract. Operational Schedule data remains available through Schedule CSV.

| # | Jira column | v0.3.20 mapping / decision |
|---:|---|---|
| 1 | Issue Type | `Epic` for phase rows; `Story` for task rows. |
| 2 | Issue Type ID | Deterministic sequential import ID generated within the CSV. Used by the workbook-style Parent relationship. It is not a Jira server issue ID. |
| 3 | Summary | Phase name for Epic; persisted Schedule task name for Story. `Not Included` rows are omitted. |
| 4 | Description | Persisted task Description plus Purpose / Goal. When non-billable effort exists, `Non-Billable Hours: n` is appended because the Jira schema has no dedicated non-billable field. |
| 5 | Reporter | **Intentionally blank.** Estimator resource/persona values are not authoritative Jira account identities. |
| 6 | Original estimate (in hours) | Total scheduled task effort = Billable Hours Budgeted + Non-Billable Hours. This also ensures non-billable-only implementation tasks are not lost. CIP-RR-008 remains authoritative that Jira estimates are expressed in hours, not seconds. |
| 7 | Remaining Estimate | `max(0, Original Estimate + Change Order Hours - Hours Used)`. |
| 8 | Outward issue link (Blocks) Issue Summary | **Deferred.** No authoritative Jira dependency relationship exists in Estimate/Schedule data. |
| 9 | Outward issue link (Blocks) Issue Type ID | **Deferred.** No authoritative target Jira issue ID exists. |
| 10 | Outward issue link (Blocks) Issue Summary 31 | **Deferred** for the same reason. |
| 11 | Outward issue link (Blocks) Issue Type ID 31 | **Deferred** for the same reason. |
| 12 | Outward issue link (Blocks) Issue Summary 32 | **Deferred** for the same reason. |
| 13 | Outward issue link (Blocks) Issue Type ID 32 | **Deferred** for the same reason. |
| 14 | Outward issue link (Blocks) Issue Summary 33 | **Deferred** for the same reason. |
| 15 | Outward issue link (Blocks) Issue Type ID 33 | **Deferred** for the same reason. |
| 16 | Outward issue link (Blocks) Issue Summary 34 | **Deferred** for the same reason. |
| 17 | Outward issue link (Blocks) Issue Type ID 34 | **Deferred** for the same reason. |
| 18 | Outward issue link (Blocks) Issue Summary 35 | **Deferred** for the same reason. |
| 19 | Outward issue link (Blocks) Issue Type ID 35 | **Deferred** for the same reason. |
| 20 | Outward issue link (Discovery - Connected) Issue Summary | **Deferred.** Discovery relationships are not represented by an authoritative Jira key/ID in the Estimate model. |
| 21 | Outward issue link (Discovery - Connected) Issue Type ID | **Deferred.** No authoritative external Jira ID exists. |
| 22 | Outward issue link (Relates) Issue Type Summary | **Deferred.** Relationship semantics/targets are not persisted. |
| 23 | Outward issue link (Relates) Issue Type ID | **Deferred.** No authoritative external Jira ID exists. |
| 24 | Outward issue link (Relates) Issue Type Summary 57 | **Deferred** for the same reason. |
| 25 | Outward issue link (Relates) Issue Type ID 57 | **Deferred** for the same reason. |
| 26 | Parent | Story rows reference the deterministic import ID of the phase Epic generated in the same CSV. Epic rows are blank. |
| 27 | Epic Name | Phase name for both Epic and its Stories, preserving workbook-style grouping. |

## Parity corrections introduced in v0.3.20

1. The Jira exporter no longer filters solely on `billable_hours_budgeted > 0`. A Schedule task with non-billable effort or change-order effort can be exported even when its billable budget is zero.
2. Jira Original Estimate now represents **total scheduled task effort** (billable + non-billable), while the non-billable classification is retained in Description.
3. Jira Remaining Estimate incorporates Change Order Hours and Hours Used from the persisted Schedule.
4. MEP and CIP now use the same export implementation after product routing is established, preserving the same 27-column header and mapping rules.
5. Schedule CSV exposes the full persisted operational schedule rather than overloading the Jira import artifact with fields Jira did not define in the workbook contract.

## Explicit non-goals / deferred integration items

The Estimator does not currently persist Jira account IDs, issue keys, dependency targets, or externally confirmed relationship semantics. Therefore v0.3.20 intentionally does not populate Reporter or columns 8–25. These fields may be populated only when a future Jira integration supplies authoritative external identities/relationships. Generating plausible values would create false project dependencies and is prohibited by the export control boundary.

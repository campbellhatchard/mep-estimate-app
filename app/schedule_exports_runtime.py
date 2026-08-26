from __future__ import annotations

import csv
import io
from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .cip_domain import _take_route, revision_product
from .cip_models import PRODUCT_CIP
from .database import get_db
from .jira_relationships import (
    JIRA_RELATIONSHIP_COLUMNS,
    jira_exportable_task,
    relationships_for_revision,
)
from .models import ScheduleTask
from .services.audit import record
from .services.schedule import schedule_metrics


JIRA_HEADERS = [
    "Issue Type",
    "Issue Type ID",
    "Summary",
    "Description",
    "Reporter",
    "Original estimate (in hours)",
    "Remaining Estimate",
    "Outward issue link (Blocks) Issue Summary",
    "Outward issue link (Blocks) Issue Type ID",
    "Outward issue link (Blocks) Issue Summary 31",
    "Outward issue link (Blocks) Issue Type ID 31",
    "Outward issue link (Blocks) Issue Summary 32",
    "Outward issue link (Blocks) Issue Type ID 32",
    "Outward issue link (Blocks) Issue Summary 33",
    "Outward issue link (Blocks) Issue Type ID 33",
    "Outward issue link (Blocks) Issue Summary 34",
    "Outward issue link (Blocks) Issue Type ID 34",
    "Outward issue link (Blocks) Issue Summary 35",
    "Outward issue link (Blocks) Issue Type ID 35",
    "Outward issue link (Discovery - Connected) Issue Summary",
    "Outward issue link (Discovery - Connected) Issue Type ID",
    "Outward issue link (Relates) Issue Type Summary",
    "Outward issue link (Relates) Issue Type ID",
    "Outward issue link (Relates) Issue Type Summary 57",
    "Outward issue link (Relates) Issue Type ID 57",
    "Parent",
    "Epic Name",
]

SCHEDULE_HEADERS = [
    "Task ID",
    "Phase",
    "Task",
    "Task Owner / Persona",
    "Description",
    "Purpose / Goal",
    "Resource Assigned",
    "Status",
    "Percent Complete",
    "Non-Billable Hours",
    "Billable Hours Budgeted",
    "Change Order Hours",
    "Hours Used",
    "Billable Hours Remaining",
    "Budget Trend / Health",
    "Estimate at Completion",
    "Comments",
    "Start Date",
    "End Date",
]

PHASES = ("Plan", "Design", "Build", "Test", "Go Live")


def _persisted_tasks(db: Session, revision_id: int) -> list[ScheduleTask]:
    return (
        db.query(ScheduleTask)
        .filter(ScheduleTask.revision_id == revision_id)
        .order_by(ScheduleTask.sort_order, ScheduleTask.id)
        .all()
    )


def _csv_response(text: str, filename: str, *, bom: bool = False) -> StreamingResponse:
    # Jira historically used plain UTF-8 and downstream imports depend on the exact
    # first header value. Schedule CSV may opt into a BOM for predictable Excel opening.
    data = text.encode("utf-8-sig" if bom else "utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _jira_description(task: ScheduleTask) -> str:
    pieces: list[str] = []
    if (task.description or "").strip():
        pieces.append(task.description.strip())
    if (task.purpose or "").strip():
        pieces.append(f"Purpose / Goal: {task.purpose.strip()}")
    # The workbook Schedule explicitly separates non-billable effort. The 27-column
    # Jira contract has no dedicated non-billable field, so retain the classification
    # in Description while Original Estimate carries total scheduled task effort.
    if float(task.non_bill_hours or 0) > 0:
        pieces.append(f"Non-Billable Hours: {float(task.non_bill_hours):g}")
    return "\n".join(pieces)


def _jira_story_tasks(tasks: list[ScheduleTask]) -> dict[str, list[ScheduleTask]]:
    return {
        phase: [
            task
            for task in tasks
            if task.phase == phase and jira_exportable_task(task)
        ]
        for phase in PHASES
    }


def _jira_issue_ids(
    story_tasks: dict[str, list[ScheduleTask]],
) -> tuple[dict[str, int], dict[int, int]]:
    """Precompute the same deterministic IDs historically assigned during CSV writing."""
    next_id = 1
    epic_ids: dict[str, int] = {}
    task_issue_ids: dict[int, int] = {}
    for phase in PHASES:
        epic_ids[phase] = next_id
        next_id += 1
        for task in story_tasks[phase]:
            task_issue_ids[task.id] = next_id
            next_id += 1
    return epic_ids, task_issue_ids


def _relationship_map(db: Session, revision_id: int):
    grouped = defaultdict(lambda: defaultdict(list))
    for relationship in relationships_for_revision(db, revision_id):
        grouped[relationship.source_task_id][relationship.relationship_type].append(relationship)
    return grouped


def _apply_jira_relationships(
    row: list,
    source_task_id: int,
    relationship_map,
    task_by_id: dict[int, ScheduleTask],
    task_issue_ids: dict[int, int],
) -> None:
    by_type = relationship_map.get(source_task_id, {})
    for relationship_type, slots in JIRA_RELATIONSHIP_COLUMNS.items():
        relationships = by_type.get(relationship_type, [])
        for relationship, (summary_col, id_col) in zip(relationships, slots):
            target = task_by_id.get(relationship.target_task_id)
            target_issue_id = task_issue_ids.get(relationship.target_task_id)
            # A relationship can become non-exportable only if the user later removes the
            # target task's effort without regenerating the Schedule. Do not emit a broken
            # Jira reference; the relationship remains visible in the editor for correction.
            if target is None or target_issue_id is None:
                continue
            row[summary_col] = target.task
            row[id_col] = target_issue_id


def register_schedule_exports(app, core) -> None:
    """Install one persisted-schedule export boundary for both MEP and CIP."""
    _take_route(app, "/estimate/{rid}/jira.csv", "GET")

    @app.get("/estimate/{rid}/schedule.csv")
    def schedule_csv(rid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        rev = core.revision_or_404(db, rid)
        tasks = _persisted_tasks(db, rev.id)
        if not tasks:
            raise HTTPException(
                409,
                "The Schedule has not been generated yet. Open the Schedule tab first, then export the persisted schedule.",
            )

        metrics = schedule_metrics(tasks)
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(SCHEDULE_HEADERS)
        for task in tasks:
            metric = metrics[task.id]
            writer.writerow(
                [
                    task.task_id,
                    task.phase,
                    task.task,
                    task.task_owner,
                    task.description,
                    task.purpose,
                    task.resource_assigned,
                    task.status,
                    round(float(metric["percent"]) * 100, 2),
                    metric["non_bill"],
                    metric["budget"],
                    metric["co"],
                    metric["used"],
                    metric["remaining"],
                    metric["trend"],
                    metric["eac"],
                    task.comments,
                    metric["start"].isoformat() if metric["start"] else "",
                    metric["end"].isoformat() if metric["end"] else "",
                ]
            )

        record(
            db,
            event_type="SCHEDULE_CSV_EXPORTED",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            reason=(
                "Exported persisted schedule without regeneration"
                + ("; schedule is marked stale" if rev.schedule_needs_refresh else "")
            ),
        )
        db.commit()
        product_prefix = "CIP-" if revision_product(db, rev) == PRODUCT_CIP else ""
        return _csv_response(
            out.getvalue(),
            f"{product_prefix}Estimate-{rev.estimate.estimate_number}-Rev-{rev.revision_no}-Schedule.csv",
            bom=True,
        )

    @app.get("/estimate/{rid}/jira.csv")
    def jira_csv(rid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        rev = core.revision_or_404(db, rid)
        tasks = _persisted_tasks(db, rev.id)
        if not tasks:
            # Existing Jira behavior generated an initial schedule when none existed.
            # This is safe because there are no persisted user edits to overwrite.
            tasks = core.generate_schedule(db, rev, replace=True)
            db.commit()

        story_tasks = _jira_story_tasks(tasks)
        epic_ids, task_issue_ids = _jira_issue_ids(story_tasks)
        task_by_id = {task.id: task for phase in PHASES for task in story_tasks[phase]}
        relationship_map = _relationship_map(db, rev.id)

        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(JIRA_HEADERS)

        for phase in PHASES:
            epic_id = epic_ids[phase]
            epic = [""] * len(JIRA_HEADERS)
            epic[0] = "Epic"
            epic[1] = epic_id
            epic[2] = phase
            epic[26] = phase
            writer.writerow(epic)

            for task in story_tasks[phase]:
                billable = float(task.billable_hours_budgeted or 0)
                non_billable = float(task.non_bill_hours or 0)
                change_order = float(task.change_order_hours or 0)
                used = float(task.hours_used or 0)
                original_estimate = billable + non_billable
                remaining = max(0.0, original_estimate + change_order - used)

                row = [""] * len(JIRA_HEADERS)
                row[0] = "Story"
                row[1] = task_issue_ids[task.id]
                row[2] = task.task
                row[3] = _jira_description(task)
                # Reporter is deliberately blank: the estimator has a resource/persona
                # name, not a Jira account identity suitable for Reporter import.
                row[5] = original_estimate
                row[6] = remaining
                _apply_jira_relationships(
                    row,
                    task.id,
                    relationship_map,
                    task_by_id,
                    task_issue_ids,
                )
                row[25] = epic_id
                row[26] = phase
                writer.writerow(row)

        relationship_count = sum(
            len(relationships)
            for by_type in relationship_map.values()
            for relationships in by_type.values()
        )
        record(
            db,
            event_type="JIRA_CSV_EXPORTED",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            reason=(
                "27-column workbook-compatible Jira export from persisted Schedule; "
                f"{relationship_count} explicit relationship record(s) evaluated"
            ),
        )
        db.commit()
        product_prefix = "CIP-" if revision_product(db, rev) == PRODUCT_CIP else ""
        return _csv_response(
            out.getvalue(),
            f"{product_prefix}Estimate-{rev.estimate.estimate_number}-Jira.csv",
        )

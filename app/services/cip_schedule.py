from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..models import EstimateRevision, ScheduleTask
from .cip_calculation import calculation
from .schedule import business_add


def generate_cip_schedule(db: Session, rev: EstimateRevision, replace: bool = True):
    lines, summary, _, _ = calculation(db, rev)
    if replace:
        (
            db.query(ScheduleTask)
            .filter(ScheduleTask.revision_id == rev.id)
            .delete(synchronize_session=False)
        )

    start = rev.project_start or rev.proposal_date or date.today()
    rev.project_start = start
    current = start
    order = 0

    for phase in ["Plan", "Design", "Build", "Test", "Go Live"]:
        phase_total = summary["phase_totals"][phase]
        phase_row = ScheduleTask(
            revision_id=rev.id,
            task_id=f"CIP-{phase.upper().replace(' ', '-')}",
            phase=phase,
            task=phase,
            task_owner="",
            description=f"{phase} phase summary generated from the CIP estimate.",
            purpose="Generated phase budget; child tasks remain the authoritative schedule detail.",
            status="Planned",
            percent_complete=0,
            non_bill_hours=float(phase_total["non_billable"]),
            billable_hours_budgeted=float(phase_total["investment"]),
            change_order_hours=0,
            hours_used=0,
            start_date=current,
            end_date=current,
            sort_order=order,
        )
        db.add(phase_row)
        order += 1

        phase_lines = [line for line in lines if line.phase == phase]
        phase_start = None
        phase_end = None
        for line in phase_lines:
            total = float(line.task_hours or 0)
            days = max(1, int(round(total / 8))) if total > 0 else 0
            task_start = current if total > 0 else None
            task_end = business_add(task_start, max(0, days - 1)) if task_start else None
            if total > 0:
                phase_start = phase_start or task_start
                phase_end = task_end
                current = business_add(task_end, 1)
            db.add(
                ScheduleTask(
                    revision_id=rev.id,
                    task_id=line.key,
                    phase=phase,
                    task=line.description if total > 0 else f"Not Included - {line.description}",
                    task_owner="",
                    description=line.trace or "",
                    purpose="Generated from the CIP calculation model.",
                    status="Planned",
                    percent_complete=0,
                    non_bill_hours=float(line.non_billable_hours or 0),
                    billable_hours_budgeted=float(line.investment_hours or 0),
                    change_order_hours=0,
                    hours_used=0,
                    start_date=task_start,
                    end_date=task_end,
                    sort_order=order,
                )
            )
            order += 1

        phase_row.start_date = phase_start or current
        phase_row.end_date = phase_end or phase_row.start_date

    rev.schedule_needs_refresh = False
    db.flush()
    return (
        db.query(ScheduleTask)
        .filter(ScheduleTask.revision_id == rev.id)
        .order_by(ScheduleTask.sort_order)
        .all()
    )

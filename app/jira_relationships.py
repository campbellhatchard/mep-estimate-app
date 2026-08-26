from __future__ import annotations

from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .database import get_db
from .jira_models import ScheduleTaskRelationship
from .models import ScheduleTask
from .services.audit import record


BLOCKS = "BLOCKS"
DISCOVERY_CONNECTED = "DISCOVERY_CONNECTED"
RELATES = "RELATES"

RELATIONSHIP_LABELS = {
    BLOCKS: "Blocks",
    DISCOVERY_CONNECTED: "Discovery - Connected",
    RELATES: "Relates",
}

# The controlled 27-column Jira workbook contract reserves exactly these outbound
# slots per Story. Do not silently truncate relationships during export.
RELATIONSHIP_CAPACITY = {
    BLOCKS: 6,
    DISCOVERY_CONNECTED: 1,
    RELATES: 2,
}

JIRA_RELATIONSHIP_COLUMNS = {
    BLOCKS: ((7, 8), (9, 10), (11, 12), (13, 14), (15, 16), (17, 18)),
    DISCOVERY_CONNECTED: ((19, 20),),
    RELATES: ((21, 22), (23, 24)),
}

LOCKED_REVISION_STATUSES = {"APPROVED", "FINAL", "SUPERSEDED"}


def jira_exportable_task(task: ScheduleTask) -> bool:
    if task.task == task.phase:
        return False
    if task.task == "Not Included" or task.task.startswith("Not Included - "):
        return False
    return (
        float(task.billable_hours_budgeted or 0) > 0
        or float(task.non_bill_hours or 0) > 0
        or float(task.change_order_hours or 0) != 0
    )


def jira_exportable_tasks(tasks: list[ScheduleTask]) -> list[ScheduleTask]:
    return [task for task in tasks if jira_exportable_task(task)]


def relationships_for_revision(
    db: Session, revision_id: int
) -> list[ScheduleTaskRelationship]:
    return (
        db.query(ScheduleTaskRelationship)
        .filter(ScheduleTaskRelationship.revision_id == revision_id)
        .order_by(
            ScheduleTaskRelationship.source_task_id,
            ScheduleTaskRelationship.relationship_type,
            ScheduleTaskRelationship.sort_order,
            ScheduleTaskRelationship.id,
        )
        .all()
    )


def _blocks_would_cycle(
    relationships: list[ScheduleTaskRelationship], source_task_id: int, target_task_id: int
) -> bool:
    graph: dict[int, set[int]] = defaultdict(set)
    for relationship in relationships:
        if relationship.relationship_type == BLOCKS:
            graph[relationship.source_task_id].add(relationship.target_task_id)
    graph[source_task_id].add(target_task_id)

    stack = [target_task_id]
    visited: set[int] = set()
    while stack:
        node = stack.pop()
        if node == source_task_id:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(graph.get(node, ()))
    return False


def _task_or_400(db: Session, task_id: int, revision_id: int) -> ScheduleTask:
    task = db.get(ScheduleTask, task_id)
    if not task or task.revision_id != revision_id:
        raise HTTPException(400, "Relationship tasks must belong to this estimate revision")
    if not jira_exportable_task(task):
        raise HTTPException(400, "Only Jira-exportable Schedule tasks can participate in relationships")
    return task


def _require_editable_revision(core, user, rev) -> None:
    core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
    if rev.status in LOCKED_REVISION_STATUSES or rev.status != "DRAFT":
        raise HTTPException(409, "Jira relationships can only be changed while the revision is Draft")


def register_jira_relationship_routes(app, core) -> None:
    @app.get("/estimate/{rid}/jira-relationships", response_class=HTMLResponse)
    def jira_relationship_page(
        rid: int, request: Request, db: Session = Depends(get_db)
    ):
        user = core.current_user(request, db)
        rev = core.revision_or_404(db, rid)
        tasks = (
            db.query(ScheduleTask)
            .filter(ScheduleTask.revision_id == rev.id)
            .order_by(ScheduleTask.sort_order, ScheduleTask.id)
            .all()
        )
        exportable = jira_exportable_tasks(tasks)
        if not tasks:
            raise HTTPException(
                409,
                "The Schedule has not been generated yet. Open the Schedule tab first.",
            )

        task_by_id = {task.id: task for task in exportable}
        relationships = [
            relationship
            for relationship in relationships_for_revision(db, rev.id)
            if relationship.source_task_id in task_by_id
            and relationship.target_task_id in task_by_id
        ]
        return core.templates.TemplateResponse(
            "jira_relationships.html",
            {
                "request": request,
                "user": user,
                "rev": rev,
                "estimate": rev.estimate,
                "tasks": exportable,
                "task_by_id": task_by_id,
                "relationships": relationships,
                "relationship_labels": RELATIONSHIP_LABELS,
                "relationship_capacity": RELATIONSHIP_CAPACITY,
                "readonly": rev.status != "DRAFT",
            },
        )

    @app.post("/estimate/{rid}/jira-relationships")
    async def save_jira_relationship(
        rid: int, request: Request, db: Session = Depends(get_db)
    ):
        user = core.current_user(request, db)
        rev = core.revision_or_404(db, rid)
        _require_editable_revision(core, user, rev)
        form = await request.form()
        action = str(form.get("action", "add")).strip().lower()

        if action == "delete":
            try:
                relationship_id = int(form.get("relationship_id") or 0)
            except (TypeError, ValueError):
                raise HTTPException(400, "Relationship ID is required")
            relationship = db.get(ScheduleTaskRelationship, relationship_id)
            if not relationship or relationship.revision_id != rev.id:
                raise HTTPException(404, "Jira relationship not found")
            old_value = (
                f"{relationship.relationship_type}:"
                f"{relationship.source_task_id}->{relationship.target_task_id}"
            )
            db.delete(relationship)
            record(
                db,
                event_type="JIRA_RELATIONSHIP_DELETED",
                user_id=user.id,
                estimate_id=rev.estimate_id,
                revision_id=rev.id,
                old_value=old_value,
                reason="Removed explicit Jira Schedule relationship",
            )
            db.commit()
            return RedirectResponse(f"/estimate/{rid}/jira-relationships", 303)

        try:
            source_task_id = int(form.get("source_task_id") or 0)
            target_task_id = int(form.get("target_task_id") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Source and target tasks are required")
        relationship_type = str(form.get("relationship_type") or "").strip().upper()
        if relationship_type not in RELATIONSHIP_CAPACITY:
            raise HTTPException(400, "Unsupported Jira relationship type")
        if source_task_id == target_task_id:
            raise HTTPException(400, "A Jira task cannot relate to itself")

        source = _task_or_400(db, source_task_id, rev.id)
        target = _task_or_400(db, target_task_id, rev.id)
        existing = relationships_for_revision(db, rev.id)
        if any(
            relationship.source_task_id == source_task_id
            and relationship.target_task_id == target_task_id
            and relationship.relationship_type == relationship_type
            for relationship in existing
        ):
            raise HTTPException(409, "This Jira relationship already exists")

        same_type = [
            relationship
            for relationship in existing
            if relationship.source_task_id == source_task_id
            and relationship.relationship_type == relationship_type
        ]
        if len(same_type) >= RELATIONSHIP_CAPACITY[relationship_type]:
            raise HTTPException(
                409,
                f"{RELATIONSHIP_LABELS[relationship_type]} supports at most "
                f"{RELATIONSHIP_CAPACITY[relationship_type]} outbound relationship(s) per Jira Story",
            )
        if relationship_type == BLOCKS and _blocks_would_cycle(
            existing, source_task_id, target_task_id
        ):
            raise HTTPException(400, "Blocks relationships cannot create a dependency cycle")

        relationship = ScheduleTaskRelationship(
            revision_id=rev.id,
            source_task_id=source_task_id,
            target_task_id=target_task_id,
            relationship_type=relationship_type,
            sort_order=len(same_type),
            created_by=user.id,
        )
        db.add(relationship)
        record(
            db,
            event_type="JIRA_RELATIONSHIP_ADDED",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            new_value=f"{relationship_type}:{source_task_id}->{target_task_id}",
            reason=f"{source.task} -> {target.task}",
        )
        db.commit()
        return RedirectResponse(f"/estimate/{rid}/jira-relationships", 303)

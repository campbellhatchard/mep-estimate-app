from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.jira_models import ScheduleTaskRelationship
from app.jira_relationships import BLOCKS, DISCOVERY_CONNECTED, RELATES, jira_exportable_task
from app.models import AuditEvent, EstimateRevision, ScheduleTask
from app.run import app


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "Admin", "password": "TestPass123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)


def _create_estimate(client: TestClient) -> int:
    response = client.post("/estimates/new", follow_redirects=False)
    assert response.status_code == 303, (response.status_code, response.text)
    return int(response.headers["location"].rsplit("/", 1)[-1])


def _generate_and_get_tasks(client: TestClient, rid: int) -> list[ScheduleTask]:
    response = client.get(f"/estimate/{rid}/schedule")
    assert response.status_code == 200, (response.status_code, response.text)
    with SessionLocal() as db:
        tasks = (
            db.query(ScheduleTask)
            .filter(ScheduleTask.revision_id == rid)
            .order_by(ScheduleTask.sort_order, ScheduleTask.id)
            .all()
        )
        exportable = [task for task in tasks if jira_exportable_task(task)]
        assert len(exportable) >= 3
        for task in exportable:
            db.expunge(task)
        return exportable


def _add_relationship(
    client: TestClient,
    rid: int,
    source_task_id: int,
    target_task_id: int,
    relationship_type: str,
):
    return client.post(
        f"/estimate/{rid}/jira-relationships",
        data={
            "action": "add",
            "source_task_id": str(source_task_id),
            "target_task_id": str(target_task_id),
            "relationship_type": relationship_type,
        },
        follow_redirects=False,
    )


def _jira_rows(client: TestClient, rid: int) -> list[list[str]]:
    response = client.get(f"/estimate/{rid}/jira.csv")
    assert response.status_code == 200, (response.status_code, response.text)
    return list(csv.reader(io.StringIO(response.text)))


def _story_row(rows: list[list[str]], summary: str) -> list[str]:
    matches = [row for row in rows[1:] if len(row) >= 27 and row[0] == "Story" and row[2] == summary]
    assert matches, f"Jira Story not found for {summary!r}"
    return matches[0]


def test_explicit_relationships_fill_reserved_jira_columns_and_are_audited():
    with TestClient(app) as client:
        _login(client)
        rid = _create_estimate(client)
        tasks = _generate_and_get_tasks(client, rid)
        source, blocked_target, related_target = tasks[:3]

        assert _add_relationship(client, rid, source.id, blocked_target.id, BLOCKS).status_code == 303
        assert _add_relationship(
            client, rid, source.id, related_target.id, DISCOVERY_CONNECTED
        ).status_code == 303
        assert _add_relationship(client, rid, source.id, related_target.id, RELATES).status_code == 303

        page = client.get(f"/estimate/{rid}/jira-relationships")
        assert page.status_code == 200
        assert "Relationships are maintained explicitly" in page.text
        assert source.task in page.text
        assert blocked_target.task in page.text

        rows = _jira_rows(client, rid)
        source_row = _story_row(rows, source.task)
        blocked_row = _story_row(rows, blocked_target.task)
        related_row = _story_row(rows, related_target.task)

        assert len(rows[0]) == 27
        assert source_row[7] == blocked_target.task
        assert source_row[8] == blocked_row[1]
        assert source_row[19] == related_target.task
        assert source_row[20] == related_row[1]
        assert source_row[21] == related_target.task
        assert source_row[22] == related_row[1]

        with SessionLocal() as db:
            assert db.query(ScheduleTaskRelationship).filter(
                ScheduleTaskRelationship.revision_id == rid
            ).count() == 3
            assert db.query(AuditEvent).filter(
                AuditEvent.revision_id == rid,
                AuditEvent.event_type == "JIRA_RELATIONSHIP_ADDED",
            ).count() == 3
            export_event = db.query(AuditEvent).filter(
                AuditEvent.revision_id == rid,
                AuditEvent.event_type == "JIRA_CSV_EXPORTED",
            ).order_by(AuditEvent.id.desc()).first()
            assert export_event is not None
            assert "3 explicit relationship record(s) evaluated" in (export_event.reason or "")


def test_self_duplicate_and_blocks_cycles_are_rejected():
    with TestClient(app) as client:
        _login(client)
        rid = _create_estimate(client)
        first, second, third = _generate_and_get_tasks(client, rid)[:3]

        response = _add_relationship(client, rid, first.id, first.id, BLOCKS)
        assert response.status_code == 400
        assert "cannot relate to itself" in response.text

        assert _add_relationship(client, rid, first.id, second.id, BLOCKS).status_code == 303
        duplicate = _add_relationship(client, rid, first.id, second.id, BLOCKS)
        assert duplicate.status_code == 409
        assert "already exists" in duplicate.text

        assert _add_relationship(client, rid, second.id, third.id, BLOCKS).status_code == 303
        cycle = _add_relationship(client, rid, third.id, first.id, BLOCKS)
        assert cycle.status_code == 400
        assert "dependency cycle" in cycle.text


def test_workbook_relationship_capacity_is_enforced_without_silent_truncation():
    with TestClient(app) as client:
        _login(client)
        rid = _create_estimate(client)
        tasks = _generate_and_get_tasks(client, rid)
        source = tasks[0]

        with SessionLocal() as db:
            max_sort = db.query(ScheduleTask).filter(ScheduleTask.revision_id == rid).count() + 100
            for index in range(7):
                db.add(
                    ScheduleTask(
                        revision_id=rid,
                        task_id=f"9.{index + 1}",
                        phase="Plan",
                        task=f"Capacity Target {index + 1}",
                        task_owner="",
                        description="",
                        purpose="",
                        status="Planned",
                        percent_complete=0,
                        non_bill_hours=0,
                        billable_hours_budgeted=1,
                        change_order_hours=0,
                        hours_used=0,
                        sort_order=max_sort + index,
                    )
                )
            db.commit()
            targets = (
                db.query(ScheduleTask)
                .filter(
                    ScheduleTask.revision_id == rid,
                    ScheduleTask.task.like("Capacity Target %"),
                )
                .order_by(ScheduleTask.id)
                .all()
            )
            target_ids = [task.id for task in targets]

        for target_id in target_ids[:6]:
            assert _add_relationship(client, rid, source.id, target_id, BLOCKS).status_code == 303
        overflow = _add_relationship(client, rid, source.id, target_ids[6], BLOCKS)
        assert overflow.status_code == 409
        assert "at most 6" in overflow.text

        rows = _jira_rows(client, rid)
        source_row = _story_row(rows, source.task)
        assert all(source_row[index] for index in (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18))


def test_schedule_regeneration_clears_task_identity_relationships():
    with TestClient(app) as client:
        _login(client)
        rid = _create_estimate(client)
        first, second = _generate_and_get_tasks(client, rid)[:2]
        assert _add_relationship(client, rid, first.id, second.id, RELATES).status_code == 303

        with SessionLocal() as db:
            assert db.query(ScheduleTaskRelationship).filter(
                ScheduleTaskRelationship.revision_id == rid
            ).count() == 1

        response = client.post(
            f"/estimate/{rid}/schedule",
            data={"action": "regenerate"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        with SessionLocal() as db:
            assert db.query(ScheduleTaskRelationship).filter(
                ScheduleTaskRelationship.revision_id == rid
            ).count() == 0


def test_locked_revision_relationships_are_read_only_and_still_export():
    with TestClient(app) as client:
        _login(client)
        rid = _create_estimate(client)
        first, second = _generate_and_get_tasks(client, rid)[:2]
        assert _add_relationship(client, rid, first.id, second.id, RELATES).status_code == 303

        with SessionLocal() as db:
            relationship = db.query(ScheduleTaskRelationship).filter(
                ScheduleTaskRelationship.revision_id == rid
            ).one()
            relationship_id = relationship.id

        assert client.post(
            f"/estimate/{rid}/status/submit", follow_redirects=False
        ).status_code == 303
        assert client.post(
            f"/estimate/{rid}/status/approve", follow_redirects=False
        ).status_code == 303

        page = client.get(f"/estimate/{rid}/jira-relationships")
        assert page.status_code == 200
        assert "read-only" in page.text
        assert "Add Jira Relationship" not in page.text

        add = _add_relationship(client, rid, second.id, first.id, RELATES)
        assert add.status_code == 409
        delete = client.post(
            f"/estimate/{rid}/jira-relationships",
            data={"action": "delete", "relationship_id": str(relationship_id)},
            follow_redirects=False,
        )
        assert delete.status_code == 409

        rows = _jira_rows(client, rid)
        first_row = _story_row(rows, first.task)
        second_row = _story_row(rows, second.task)
        assert first_row[21] == second.task
        assert first_row[22] == second_row[1]

        with SessionLocal() as db:
            revision = db.get(EstimateRevision, rid)
            assert revision.status == "APPROVED"
            assert db.get(ScheduleTaskRelationship, relationship_id) is not None

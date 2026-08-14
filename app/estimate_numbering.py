from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import Integer, String, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base, get_db
from .models import ConfigItem, Estimate, EstimateCustomApplication, EstimateRevision
from .services.audit import record

DEFAULT_APP_TIMEZONE = "America/Chicago"


class EstimateNumberSequence(Base):
    """Atomic monthly sequence used to allocate YYYYMMNNN estimate numbers."""

    __tablename__ = "estimate_number_sequences"

    period_key: Mapped[str] = mapped_column(String(6), primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EstimateNumberExhausted(RuntimeError):
    pass


def current_business_date() -> date:
    timezone_name = os.getenv("APP_TIMEZONE", DEFAULT_APP_TIMEZONE)
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Invalid APP_TIMEZONE: {timezone_name}") from exc
    return datetime.now(timezone).date()


def next_estimate_number(db: Session, business_date: date | None = None) -> str:
    """Return the next estimate number in YYYYMMNNN format.

    The UPSERT increments a single row per year/month. PostgreSQL and modern SQLite
    both execute this statement atomically, so two concurrent creators cannot receive
    the same monthly sequence value.
    """

    business_date = business_date or current_business_date()
    period_key = business_date.strftime("%Y%m")

    # A sequence row is held by the transaction until commit. If two requests arrive
    # simultaneously, the database serializes the update for this period_key.
    result = db.execute(
        text(
            """
            INSERT INTO estimate_number_sequences (period_key, last_number)
            VALUES (:period_key, 1)
            ON CONFLICT(period_key)
            DO UPDATE SET last_number = estimate_number_sequences.last_number + 1
            RETURNING last_number
            """
        ),
        {"period_key": period_key},
    )
    sequence = int(result.scalar_one())

    if sequence > 999:
        raise EstimateNumberExhausted(
            f"Estimate number capacity for {period_key} has been exhausted (999 estimates)."
        )

    return f"{period_key}{sequence:03d}"


def _remove_legacy_create_route(app) -> None:
    """Remove the v0.1/v0.2 create route before registering the numbered version."""

    for route in list(app.router.routes):
        methods = getattr(route, "methods", set()) or set()
        if getattr(route, "path", None) == "/estimates/new" and "POST" in methods:
            app.router.routes.remove(route)


def register_numbered_estimate_route(app, core) -> None:
    _remove_legacy_create_route(app)

    @app.post("/estimates/new")
    def create_numbered_estimate(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")

        business_day = current_business_date()
        try:
            number = next_estimate_number(db, business_day)
        except EstimateNumberExhausted as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        estimate = Estimate(estimate_number=number, created_by=user.id)
        db.add(estimate)
        db.flush()

        config_version = core.active_config(db)
        entity = (
            db.query(ConfigItem)
            .filter(
                ConfigItem.config_version_id == config_version.id,
                ConfigItem.category == "Entity",
                ConfigItem.active.is_(True),
            )
            .order_by(ConfigItem.sort_order)
            .first()
        )
        revision = EstimateRevision(
            estimate_id=estimate.id,
            revision_no=1,
            status="DRAFT",
            config_version_id=config_version.id,
            engine_version=core.ENGINE_VERSION,
            proposal_date=business_day,
            project_start=business_day,
            entity=entity.label if entity else "",
            created_by=user.id,
        )
        db.add(revision)
        db.flush()

        core.sync_catalog(db, revision, revision.erp, force=True)
        for i in range(20):
            db.add(
                EstimateCustomApplication(
                    revision_id=revision.id,
                    description="",
                    complexity="No Config",
                    sort_order=i,
                )
            )

        record(
            db,
            event_type="ESTIMATE_CREATED",
            user_id=user.id,
            estimate_id=estimate.id,
            revision_id=revision.id,
            config_version_id=config_version.id,
            new_value=number,
        )
        core.recalculate_and_store(db, revision)
        db.commit()
        return RedirectResponse(f"/estimate/{revision.id}", 303)

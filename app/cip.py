from __future__ import annotations

from typing import Callable
from sqlalchemy.orm import Session

from .cip_domain import (
    _take_route, active_config_for_product, revision_product, seed_cip_database,
)
from .cip_models import PRODUCT_CIP, PRODUCT_MEP
from .database import SessionLocal
from .models import EstimateRevision
from .services.cip_schedule import generate_cip_schedule
from .cip_routes_repository import register_repository_routes
from .cip_routes_estimate import register_estimate_routes
from .cip_routes_detail import register_detail_routes
from .cip_routes_exports import register_export_routes
from .cip_routes_config import register_config_routes


def register_cip(app, core, mep_schedule_generator: Callable):
    """Register CIP without modifying the locked MEP calculation engine."""
    _take_route(app, "/estimates", "GET")
    mep_create = _take_route(app, "/estimates/new", "POST")
    mep_estimate_get = _take_route(app, "/estimate/{rid}", "GET")
    mep_estimate_post = _take_route(app, "/estimate/{rid}", "POST")
    mep_new_revision = _take_route(app, "/estimate/{rid}/new-revision", "POST")
    mep_detail_get = _take_route(app, "/estimate/{rid}/detail", "GET")
    mep_detail_post = _take_route(app, "/estimate/{rid}/detail", "POST")
    mep_calc_get = _take_route(app, "/estimate/{rid}/calculations", "GET")
    mep_calc_post = _take_route(app, "/estimate/{rid}/calculations", "POST")
    mep_pdf = _take_route(app, "/estimate/{rid}/pdf", "GET")
    mep_jira = _take_route(app, "/estimate/{rid}/jira.csv", "GET")
    _take_route(app, "/data", "GET")
    _take_route(app, "/data/version/new", "POST")
    _take_route(app, "/data/version/{vid}/activate", "POST")

    # Legacy MEP code must always resolve the active MEP configuration, even when a
    # separate active CIP configuration exists.
    core.active_config = lambda db: active_config_for_product(db, PRODUCT_MEP)

    @app.on_event("startup")
    def startup_cip():
        db = SessionLocal()
        try:
            seed_cip_database(db)
        finally:
            db.close()

    def product_schedule(db: Session, rev: EstimateRevision, replace=True):
        if revision_product(db, rev) == PRODUCT_CIP:
            return generate_cip_schedule(db, rev, replace=replace)
        return mep_schedule_generator(db, rev, replace=replace)

    core.generate_schedule = product_schedule
    register_repository_routes(app, core, mep_create)
    register_estimate_routes(app, core, mep_estimate_get, mep_estimate_post, mep_new_revision)
    register_detail_routes(app, core, mep_detail_get, mep_detail_post, mep_calc_get, mep_calc_post)
    register_export_routes(app, core, mep_pdf, mep_jira)
    register_config_routes(app, core)

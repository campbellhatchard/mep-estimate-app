from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from app import cip_domain
from app.route_architecture import (
    FINAL_ROUTE_OWNERS,
    assert_final_route_owners,
    matching_routes,
    take_route,
)
from app.run import app


def test_release_uses_single_bootstrap_and_explicit_final_route_owners():
    assert app.version == "0.3.24.0"
    assert_final_route_owners(app)

    for owner in FINAL_ROUTE_OWNERS:
        routes = matching_routes(app, owner.path, owner.method)
        assert len(routes) == 1, f"{owner.method} {owner.path} is not uniquely registered"
        endpoint = routes[0].endpoint
        assert endpoint.__module__ == owner.module


def test_cip_domain_exports_the_shared_route_interceptor_for_legacy_callers():
    # Existing route modules still import `_take_route` from cip_domain. The infrastructure
    # implementation itself now lives in route_architecture, so those imports remain compatible
    # without keeping route-manipulation code inside the CIP business-domain module.
    assert cip_domain._take_route is take_route


def test_shared_route_interceptor_rejects_ambiguous_duplicate_registration():
    candidate = FastAPI()

    @candidate.get("/duplicate")
    def first():
        return {"owner": "first"}

    @candidate.get("/duplicate")
    def second():
        return {"owner": "second"}

    with pytest.raises(RuntimeError, match="Route interception is ambiguous"):
        take_route(candidate, "/duplicate", "GET")


def test_route_removal_implementation_is_centralized():
    offenders: list[str] = []
    for path in Path("app").rglob("*.py"):
        if path.name == "route_architecture.py":
            continue
        text = path.read_text(encoding="utf-8")
        if ".router.routes.remove(" in text or "def _take_route(" in text:
            offenders.append(str(path))
    assert offenders == [], f"Ad-hoc route removal remains in: {offenders}"


def test_run_module_is_thin_and_architecture_is_documented():
    run = Path("app/run.py").read_text(encoding="utf-8")
    bootstrap = Path("app/application_bootstrap.py").read_text(encoding="utf-8")
    architecture = Path("ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "configure_application(app, core)" in run
    assert "register_cip(" not in run
    assert "register_sow(" not in run
    assert "_register_estimate_capabilities" in bootstrap
    assert "_register_sow_capabilities" in bootstrap
    assert "assert_final_route_owners(app)" in bootstrap

    for heading in (
        "Application bootstrap",
        "Module ownership",
        "Shared route ownership",
        "Historical reproducibility invariants",
    ):
        assert heading in architecture

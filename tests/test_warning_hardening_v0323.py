from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.templating import Jinja2Templates

from app import main as core
from app import sow_routes
from app.application_bootstrap import RELEASE_VERSION
from app.database import Base
from app.framework_compat import _compat_on_event, _compat_template_response
from app.run import app
from app.warning_hardening import _is_utcnow_callable


def test_v0323_hardening_boundary_remains_active():
    assert app.version == RELEASE_VERSION
    assert FastAPI.on_event is _compat_on_event
    assert Jinja2Templates.TemplateResponse is _compat_template_response


def test_sqlalchemy_defaults_no_longer_capture_deprecated_utcnow():
    offenders: list[str] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for label, default in (("default", column.default), ("onupdate", column.onupdate)):
                if default is not None and _is_utcnow_callable(getattr(default, "arg", None)):
                    offenders.append(f"{table.name}.{column.name}:{label}")
    assert offenders == []


def test_identity_map_sensitive_rebuilds_use_hardened_orm_paths():
    assert core.sync_catalog.__module__ == "app.warning_hardening"
    assert sow_routes._replace_child_rows.__module__ == "app.warning_hardening"


def test_ci_uses_node24_actions_and_surfaces_skipped_test_reasons():
    workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "pytest -q -ra --strict-config" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow


def test_target_warning_classes_are_release_blocking():
    config = Path("pytest.ini").read_text(encoding="utf-8")
    assert "on_event is deprecated" in config
    assert "datetime\\.datetime\\.utcnow" in config
    assert "The `name` is not the first parameter anymore" in config
    assert "Identity map already had an identity" in config

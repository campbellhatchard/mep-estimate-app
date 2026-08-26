from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from .database import Base
from .models import ConfigItem, EstimateApplication
from .runtime_time import utc_now
from .sow_models import SOWDevice, SOWHypercareLocation


class _NaiveUTCDateTime(datetime):
    """Compatibility datetime with the legacy naive-UTC `utcnow()` contract."""

    @classmethod
    def utcnow(cls):  # noqa: D102 - compatibility with legacy application calls
        return utc_now()


def _is_utcnow_callable(value: Any) -> bool:
    candidate = value
    for _ in range(4):
        if candidate is None:
            return False
        if getattr(candidate, "__name__", "") == "utcnow":
            return True
        candidate = getattr(candidate, "__wrapped__", None)
    return False


def _replace_deprecated_column_defaults() -> None:
    """Replace captured `datetime.utcnow` SQLAlchemy defaults without changing schema.

    SQLAlchemy wraps zero-argument default callables with a context argument. Replacing
    only the callable `arg` preserves the existing ColumnDefault/onupdate objects and the
    database's timezone-naive UTC storage contract.
    """
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for default in (column.default, column.onupdate):
                if default is not None and _is_utcnow_callable(getattr(default, "arg", None)):
                    default.arg = lambda _ctx=None: utc_now()


def _replace_loaded_datetime_bindings() -> None:
    """Redirect legacy module-local `datetime.utcnow()` calls to the UTC helper."""
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("app.") or module is None:
            continue
        if getattr(module, "datetime", None) is datetime:
            setattr(module, "datetime", _NaiveUTCDateTime)


def _install_catalog_rebuild(core) -> None:
    """Rebuild MEP catalog rows without leaving deleted identities in the Session map."""

    def sync_catalog(db, rev, erp, force=False):
        parent = core.slug(erp)
        existing = (
            db.query(EstimateApplication)
            .filter(EstimateApplication.revision_id == rev.id)
            .all()
        )
        if existing and not force:
            return
        if force and existing:
            for row in existing:
                db.delete(row)
            db.flush()
            # Ensure any previously-loaded relationship is refreshed from the rebuilt rows.
            try:
                db.expire(rev, ["applications"])
            except Exception:
                pass

        apps = (
            db.query(ConfigItem)
            .filter(
                ConfigItem.config_version_id == rev.config_version_id,
                ConfigItem.category == "ERP Application",
                ConfigItem.parent_key == parent,
                ConfigItem.active.is_(True),
            )
            .order_by(ConfigItem.sort_order)
            .all()
        )
        packages = (
            db.query(ConfigItem)
            .filter(
                ConfigItem.config_version_id == rev.config_version_id,
                ConfigItem.category == "ERP Package",
                ConfigItem.parent_key == parent,
                ConfigItem.active.is_(True),
            )
            .order_by(ConfigItem.sort_order)
            .all()
        )
        for index, item in enumerate(apps):
            db.add(
                EstimateApplication(
                    revision_id=rev.id,
                    kind="APPLICATION",
                    catalog_key=item.key,
                    label=item.label,
                    config_type="No Config",
                    sort_order=index,
                )
            )
        for index, item in enumerate(packages):
            db.add(
                EstimateApplication(
                    revision_id=rev.id,
                    kind="PACKAGE",
                    catalog_key=item.key,
                    label=item.label,
                    config_type="No Config",
                    sort_order=index,
                )
            )
        db.flush()

    core.sync_catalog = sync_catalog


def _install_sow_child_rebuild() -> None:
    """Replace SOW child rows through ORM state transitions rather than bulk deletion."""
    from . import sow_routes

    def replace_child_rows(db, sow, form, user, rev):
        old_h_rows = list(sow.hypercare_locations)
        old_d_rows = list(sow.devices)
        old_h = json.dumps(
            [
                [row.description, row.country, row.support_type, float(row.allocated_hours or 0)]
                for row in old_h_rows
            ],
            ensure_ascii=False,
        )
        old_d = json.dumps(
            [[row.device_type, row.make_model, row.os_version] for row in old_d_rows],
            ensure_ascii=False,
        )

        for row in old_h_rows:
            db.delete(row)
        for row in old_d_rows:
            db.delete(row)
        db.flush()

        descs = form.getlist("hypercare_description")
        countries = form.getlist("hypercare_country")
        support = form.getlist("hypercare_support_type")
        hours = form.getlist("hypercare_hours")
        new_h = []
        for index in range(max(len(descs), len(countries), len(support), len(hours))):
            description = str(descs[index] if index < len(descs) else "").strip()
            country = str(countries[index] if index < len(countries) else "").strip()
            support_type = str(
                support[index] if index < len(support) else "Remote"
            ).strip() or "Remote"
            allocated = sow_routes._as_float(hours[index] if index < len(hours) else 0)
            if not description and not country and allocated == 0:
                continue
            row = SOWHypercareLocation(
                sow_id=sow.id,
                description=description,
                country=country,
                support_type=(
                    support_type
                    if support_type in sow_routes.SUPPORT_TYPES
                    else "Remote"
                ),
                allocated_hours=allocated,
                sort_order=index,
            )
            db.add(row)
            new_h.append([description, country, row.support_type, allocated])
        sow_routes._audit_field(
            db,
            user,
            rev,
            sow,
            "HYPERCARE_LOCATIONS",
            old_h,
            json.dumps(new_h, ensure_ascii=False),
        )

        types = form.getlist("device_type")
        models = form.getlist("device_make_model")
        operating_systems = form.getlist("device_os_version")
        new_d = []
        for index in range(max(len(types), len(models), len(operating_systems))):
            device_type = str(
                types[index] if index < len(types) else "Handheld Unit"
            ).strip() or "Handheld Unit"
            make_model = str(models[index] if index < len(models) else "").strip()
            os_version = str(
                operating_systems[index] if index < len(operating_systems) else ""
            ).strip()
            if not make_model:
                continue
            row = SOWDevice(
                sow_id=sow.id,
                device_type=(
                    device_type if device_type in sow_routes.DEVICE_TYPES else "Other"
                ),
                make_model=make_model,
                os_version=os_version,
                sort_order=index,
            )
            db.add(row)
            new_d.append([row.device_type, make_model, os_version])
        sow_routes._audit_field(
            db,
            user,
            rev,
            sow,
            "DEVICES",
            old_d,
            json.dumps(new_d, ensure_ascii=False),
        )

    sow_routes._replace_child_rows = replace_child_rows


def install_warning_hardening(core) -> None:
    """Install behavior-neutral warning fixes before routes or startup tasks execute."""
    _replace_deprecated_column_defaults()
    _replace_loaded_datetime_bindings()
    _install_catalog_rebuild(core)
    _install_sow_child_rebuild()

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Iterable

from sqlalchemy.orm import Session

from ..cip_models import (
    CIPNonBillableAllocation,
    CIPRevisionInput,
    CIPScopeItem,
)
from ..models import CalculationAdjustment, ConfigItem, EstimateRevision


CIP_ENGINE_VERSION = "CIP-1.0.0"

STANDARD_CATEGORIES = ("DESKTOP", "MOBILE", "INTEGRATION")
CUSTOM_SLOT_COUNTS = {
    "CUSTOM_DESKTOP": 16,
    "CUSTOM_MOBILE": 16,
    "REPORT": 16,
}


def xrnd(value: float, digits: int = 0) -> float:
    quantum = Decimal("1") if digits == 0 else Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


class CIPConfig:
    def __init__(self, db: Session, version_id: int):
        self.items = (
            db.query(ConfigItem)
            .filter(ConfigItem.config_version_id == version_id)
            .all()
        )
        self.by_cat: dict[str, list[ConfigItem]] = {}
        for item in self.items:
            self.by_cat.setdefault(item.category, []).append(item)
        for values in self.by_cat.values():
            values.sort(key=lambda x: (x.sort_order, x.label))

    def labels(self, category: str) -> list[str]:
        return [x.label for x in self.by_cat.get(category, []) if x.active]

    def param(self, key: str) -> float:
        for item in self.by_cat.get("CIP Parameter", []):
            if item.key == key and item.value_number is not None:
                return float(item.value_number)
        raise KeyError(f"Required CIP configuration parameter missing: {key}")

    def item_by_label(self, category: str, label: str, parent: str | None = None):
        target = (label or "").strip().casefold()
        for item in self.by_cat.get(category, []):
            if not item.active:
                continue
            if parent is not None and item.parent_key != parent:
                continue
            if item.label.strip().casefold() == target:
                return item
        return None

    def item_by_key(self, category: str, key: str):
        for item in self.by_cat.get(category, []):
            if item.active and item.key == key:
                return item
        return None

    def number_by_label(self, category: str, label: str, parent: str | None = None) -> float:
        item = self.item_by_label(category, label, parent)
        if not item or item.value_number is None:
            raise KeyError(f"Required CIP configuration lookup missing: {category} / {label}")
        return float(item.value_number)

    def json_item(self, item: ConfigItem | None) -> dict:
        if not item or not item.value_text:
            return {}
        try:
            return json.loads(item.value_text)
        except Exception:
            return {}

    def latest_release(self) -> ConfigItem:
        rows = [x for x in self.by_cat.get("CIP Release", []) if x.active]
        if not rows:
            raise KeyError("No active CIP release is configured")
        return max(rows, key=lambda x: (float(x.value_number or 0), x.sort_order, x.id))


@dataclass
class CIPDetailLine:
    key: str
    section: str
    definition: str
    config_type: str
    base_hours: float
    added_hours: float
    development_hours: float
    unit_testing: float
    test_class: int
    base_solution_test: float
    ihu: float
    lot_serial: float
    food_pharma: float
    location_dimension: float
    setup_test_data: float
    monitored_session: float
    testing_adjustment: float
    testing_notes: str
    testing_total: float
    total_effort: float
    app_count: int = 0
    application_integration_hours: float = 0.0
    adjustment_notes: str = ""


@dataclass
class CIPCalcLine:
    key: str
    phase: str
    description: str
    standard_hours: float
    adjust_hours: float
    investment_hours: float
    non_billable_hours: float
    task_hours: float
    adjust_notes: str = ""
    non_billable_notes: str = ""
    trace: str = ""


def _test_modifiers(
    cfg: CIPConfig,
    inp: CIPRevisionInput,
    base_test: float,
    development_hours: float,
    *,
    label_rules: bool = False,
):
    if base_test <= 0:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    ihu = base_test * cfg.param("TEST_IHU_FACTOR") if inp.test_ihu else 0.0
    lot = base_test * cfg.param("TEST_LOT_SERIAL_FACTOR") if inp.test_lot_serial else 0.0
    food_factor = cfg.param("LABEL_TEST_FOOD_PHARMA_FACTOR") if label_rules else cfg.param("TEST_FOOD_PHARMA_FACTOR")
    food = base_test * food_factor if inp.test_food_pharma else 0.0
    location = base_test * cfg.param("TEST_LOCATION_FACTOR") if inp.test_location_dimension else 0.0
    setup = (
        cfg.param("TEST_SETUP_DATA_FIXED_HOURS") + base_test * cfg.param("TEST_SETUP_DATA_FACTOR")
        if inp.test_setup_customer_data and development_hours > 0
        else 0.0
    )
    monitored_factor = cfg.param("LABEL_TEST_MONITORED_FACTOR") if label_rules else cfg.param("TEST_MONITORED_FACTOR")
    monitored = base_test * monitored_factor if inp.test_monitored_session else 0.0
    return ihu, lot, food, location, setup, monitored


def _complexity(cfg: CIPConfig, category: str, label: str) -> tuple[float, float]:
    item = cfg.item_by_label(category, label)
    if not item:
        raise KeyError(f"Missing CIP complexity: {category}/{label}")
    meta = cfg.json_item(item)
    return float(item.value_number or 0), float(meta.get("test_factor", 0))


def _active_scope(db: Session, rev_id: int, category: str, limit: int | None = None) -> list[CIPScopeItem]:
    q = (
        db.query(CIPScopeItem)
        .filter(CIPScopeItem.revision_id == rev_id, CIPScopeItem.category == category)
        .order_by(CIPScopeItem.sort_order, CIPScopeItem.id)
    )
    rows = q.all()
    return rows[:limit] if limit is not None else rows


def detail_calculation(db: Session, rev: EstimateRevision):
    inp = db.get(CIPRevisionInput, rev.id)
    if not inp:
        raise KeyError(f"CIP inputs missing for revision {rev.id}")
    cfg = CIPConfig(db, rev.config_version_id)
    unit_factor = cfg.param("UNIT_TEST_FACTOR")
    lines: list[CIPDetailLine] = []

    def append_line(
        item: CIPScopeItem,
        section: str,
        base: float,
        base_test: float,
        *,
        test_class: int = 0,
        label_rules: bool = False,
        app_integration: float = 0.0,
        include_generic_modifiers: bool = True,
    ):
        dev = float(base) + float(item.added_hours or 0)
        unit = xrnd(dev * unit_factor, 0) if dev else 0.0
        if include_generic_modifiers:
            ihu, lot, food, location, setup, monitored = _test_modifiers(
                cfg, inp, base_test, dev, label_rules=label_rules
            )
        else:
            ihu = lot = food = location = setup = monitored = 0.0
        test_total = (
            base_test + ihu + lot + food + location + setup + monitored
            + float(item.testing_adjustment or 0)
        )
        lines.append(
            CIPDetailLine(
                key=f"{item.category}:{item.catalog_key}",
                section=section,
                definition=item.description.strip() or item.label,
                config_type=item.config_type,
                base_hours=float(base),
                added_hours=float(item.added_hours or 0),
                development_hours=dev,
                unit_testing=unit,
                test_class=test_class,
                base_solution_test=float(base_test),
                ihu=ihu,
                lot_serial=lot,
                food_pharma=food,
                location_dimension=location,
                setup_test_data=setup,
                monitored_session=monitored,
                testing_adjustment=float(item.testing_adjustment or 0),
                testing_notes=item.testing_notes or "",
                testing_total=test_total,
                total_effort=dev + unit + test_total + app_integration,
                app_count=int(item.app_count or 0),
                application_integration_hours=float(app_integration),
                adjustment_notes=item.adjustment_notes or "",
            )
        )

    for item in _active_scope(db, rev.id, "DESKTOP"):
        cat = cfg.item_by_key("CIP Desktop Application", item.catalog_key)
        baseline = float(cat.value_number or 0) if cat else 0.0
        base = baseline if item.config_type == "Baseline" else (cfg.param("STANDARD_MOD_REQUIRED_HOURS") if item.config_type == "Mod Required" else 0.0)
        dev = base + float(item.added_hours or 0)
        test_class = 0 if dev == 0 else (1 if dev < cfg.param("STANDARD_MOD_REQUIRED_HOURS") else 2)
        release_factor = float(cfg.json_item(cat).get("test_factor", 0.75))
        if test_class == 2:
            base_test = dev * inp.base_test_pct * release_factor
        elif test_class == 1:
            base_test = dev * inp.base_test_pct * cfg.param("DESKTOP_BASELINE_SMALL_CHANGE_FACTOR") * release_factor
        else:
            base_test = 0.0
        append_line(item, "Desktop Applications", base, base_test, test_class=test_class)

    for item in _active_scope(db, rev.id, "CUSTOM_DESKTOP", CUSTOM_SLOT_COUNTS["CUSTOM_DESKTOP"]):
        base, test_factor = _complexity(cfg, "CIP Custom Complexity", item.config_type)
        dev = base + float(item.added_hours or 0)
        append_line(item, "Custom Desktop Applications", base, dev * inp.base_test_pct * test_factor if dev else 0.0)

    for item in _active_scope(db, rev.id, "MOBILE"):
        cat = cfg.item_by_key("CIP Mobile Application", item.catalog_key)
        baseline = float(cat.value_number or 0) if cat else 0.0
        base = baseline if item.config_type == "Baseline" else (cfg.param("STANDARD_MOD_REQUIRED_HOURS") if item.config_type == "Mod Required" else 0.0)
        dev = base + float(item.added_hours or 0)
        test_class = 0 if dev == 0 else (1 if dev < cfg.param("STANDARD_MOD_REQUIRED_HOURS") else 2)
        release_factor = float(cfg.json_item(cat).get("test_factor", 0.75))
        if test_class == 2:
            base_test = dev * inp.base_test_pct * release_factor
        elif test_class == 1:
            base_test = dev * inp.base_test_pct * cfg.param("MOBILE_BASELINE_SMALL_CHANGE_FACTOR") * release_factor
        else:
            base_test = 0.0
        append_line(item, "Mobile Applications", base, base_test, test_class=test_class)

    for item in _active_scope(db, rev.id, "CUSTOM_MOBILE", CUSTOM_SLOT_COUNTS["CUSTOM_MOBILE"]):
        base, test_factor = _complexity(cfg, "CIP Custom Complexity", item.config_type)
        dev = base + float(item.added_hours or 0)
        append_line(item, "Custom Mobile Applications", base, dev * cfg.param("CUSTOM_MOBILE_TEST_BASE_FACTOR") * test_factor if dev else 0.0)

    for item in _active_scope(db, rev.id, "REPORT", CUSTOM_SLOT_COUNTS["REPORT"]):
        base = cfg.number_by_label("CIP Report Complexity", item.config_type)
        dev = base + float(item.added_hours or 0)
        append_line(item, "Reporting Development", base, dev * cfg.param("REPORT_TEST_BASE_FACTOR") if dev else 0.0)

    for item in _active_scope(db, rev.id, "LABEL", max(0, inp.label_count)):
        base = cfg.param("LABEL_DEV_HOURS")
        dev = base + float(item.added_hours or 0)
        append_line(item, "Labels", base, dev * cfg.param("LABEL_TEST_BASE_FACTOR"), label_rules=True)

    for item in _active_scope(db, rev.id, "INTEGRATION"):
        cat = cfg.item_by_key("CIP Integration", item.catalog_key)
        baseline = float(cat.value_number or 0) if cat else 0.0
        base = baseline if item.config_type == "Baseline" else (cfg.param("STANDARD_MOD_REQUIRED_HOURS") if item.config_type == "Mod Required" else 0.0)
        dev = base + float(item.added_hours or 0)
        append_line(item, "Baseline Integrations", base, dev * cfg.param("INTEGRATION_TEST_BASE_FACTOR") if dev else 0.0)

    for item in _active_scope(db, rev.id, "CUSTOM_BOOMI", max(0, inp.custom_boomi_count)):
        base = cfg.param("BOOMI_CUSTOM_DEV_HOURS")
        dev = base + float(item.added_hours or 0)
        append_line(item, "Custom Boomi Integrations", base, dev * cfg.param("BOOMI_CUSTOM_TEST_BASE_FACTOR"))

    for item in _active_scope(db, rev.id, "REST", max(0, inp.rest_interface_count)):
        base = cfg.param("REST_SERVICE_DEV_HOURS")
        dev = base + float(item.added_hours or 0)
        app_count = max(0, int(item.app_count or 0))
        app_effort = 0.0
        if app_count > 0:
            app_effort = cfg.param("REST_FIRST_APP_HOURS") + max(0, app_count - 1) * cfg.param("REST_ADDITIONAL_APP_HOURS")
        app_effort += float(item.integration_added_hours or 0)
        append_line(item, "RESTful Interfaces", base, (dev + app_effort) * cfg.param("REST_TEST_FACTOR") if (dev + app_effort) else 0.0, app_integration=app_effort, include_generic_modifiers=False)

    sections: dict[str, dict] = {}
    for section in [
        "Desktop Applications", "Custom Desktop Applications", "Mobile Applications",
        "Custom Mobile Applications", "Reporting Development", "Labels",
        "Baseline Integrations", "Custom Boomi Integrations", "RESTful Interfaces",
    ]:
        rows = [x for x in lines if x.section == section]
        sections[section] = {
            "count": sum(1 for x in rows if x.base_hours > 0),
            "base": sum(x.base_hours for x in rows),
            "added": sum(x.added_hours for x in rows),
            "development": sum(x.development_hours for x in rows),
            "unit": sum(x.unit_testing for x in rows),
            "testing": sum(x.testing_total for x in rows),
            "app_integration": sum(x.application_integration_hours for x in rows),
            "total": sum(x.total_effort for x in rows),
        }
    return lines, sections

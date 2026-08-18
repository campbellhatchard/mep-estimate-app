from __future__ import annotations

from .database import SessionLocal
from .sow_template_reconcile import reconcile_controlled_sow_template


def register_sow_template_reconciliation(app) -> None:
    @app.on_event("startup")
    def reconcile_sow_templates_on_startup():
        db = SessionLocal()
        try:
            reconcile_controlled_sow_template(db)
        finally:
            db.close()

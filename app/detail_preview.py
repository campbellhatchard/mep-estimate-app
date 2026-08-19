from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .cip_domain import revision_product
from .cip_models import PRODUCT_MEP
from .database import get_db
from .models import DetailAdjustment
from .services.calculation_v101 import calculation as mep_calculation


LOCKED = {"APPROVED", "FINAL", "SUPERSEDED"}
EDIT_ROLES = ("ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def register_detail_preview(app, core) -> None:
    @app.post("/estimate/{rid}/detail/preview")
    async def detail_preview(rid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, *EDIT_ROLES)
        rev = core.revision_or_404(db, rid)

        if rev.status in LOCKED:
            return JSONResponse({"detail": "Revision is locked"}, status_code=409)
        if revision_product(db, rev) != PRODUCT_MEP:
            return JSONResponse({"detail": "Live Mod Hours preview is available on MEP Estimate Detail."}, status_code=400)

        form = await request.form()
        count = int(form.get("line_count", 0) or 0)
        existing = {
            row.line_key: row
            for row in db.query(DetailAdjustment)
            .filter(DetailAdjustment.revision_id == rev.id)
            .all()
        }

        for idx in range(count):
            key = str(form.get(f"line_key_{idx}", "")).strip()
            if not key:
                continue
            row = existing.get(key)
            if not row:
                row = DetailAdjustment(
                    revision_id=rev.id,
                    line_key=key,
                    description="",
                    mod_hours=0,
                    notes="",
                )
                db.add(row)
                existing[key] = row
            row.mod_hours = _float(form.get(f"mod_{idx}", 0), 0.0)
            row.description = str(form.get(f"description_{idx}", row.description or ""))
            row.notes = str(form.get(f"notes_{idx}", row.notes or ""))

        factor_raw = str(form.get("unit_test_factor_override", "")).strip()
        if factor_raw:
            factor = _float(factor_raw, -1.0)
            if factor < 0 or factor > 1:
                db.rollback()
                return JSONResponse(
                    {"detail": {"message": "Unit Testing Factor must be between 0 and 1.", "fields": ["unit_test_factor_override"]}},
                    status_code=422,
                )
            rev.unit_test_factor_override = factor
        else:
            rev.unit_test_factor_override = None

        db.flush()
        calc_lines, summary, detail_lines, summaries = mep_calculation(db, rev)
        payload = {
            "rows": [
                {
                    "key": line.key,
                    "base": line.base_hours,
                    "mod": line.mod_hours,
                    "dev": line.dev_subtotal,
                    "unit": line.unit_testing,
                    "total": line.total,
                    "error": line.error,
                }
                for line in detail_lines
            ],
            "sections": summaries,
            "estimate": {
                "hours": summary["hours"],
                "fees": summary["fees"],
            },
            "calculation_rows": [
                {
                    "key": line.key,
                    "standard": line.standard_hours,
                    "extended": line.extended_hours,
                }
                for line in calc_lines
            ],
        }
        db.rollback()
        return payload

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .cip_domain import _take_route
from .database import get_db
from .sow_models import SOWTemplateVersion


def register_tools_admin_runtime(app, core) -> None:
    """Complete the Tools Admin boundary for the one legacy SOW-template route.

    Product-aware Calculation Data routes already implement ADMIN/TOOLS_ADMIN in
    `cip_routes_config.py`, and four-family SOW upload/activation is implemented in
    `small_project_template_admin.py`. The shared template-download route remains in
    the legacy SOW module, so replace only that endpoint here.
    """
    _take_route(app, "/admin/sow-templates/{tid}/download", "GET")

    @app.get("/admin/sow-templates/{tid}/download")
    def download_sow_template(
        tid: int, request: Request, db: Session = Depends(get_db)
    ):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "TOOLS_ADMIN")
        row = db.get(SOWTemplateVersion, tid)
        if not row:
            raise HTTPException(404, "SOW template version not found")
        return Response(
            row.content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{row.filename}"'},
        )

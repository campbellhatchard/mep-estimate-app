from __future__ import annotations

from sqlalchemy.orm import Session

from .models import EstimateRevision
from .sow_models import SOW
from . import sow_word_control
from .small_project_workflow import (
    is_small_project_sow,
    render_small_project_docx,
    render_small_project_pdf,
    verify_small_project_approved_content,
)

_installed = False


def install_small_project_word_dispatch() -> None:
    """Extend the existing controlled Word boundary without replacing its controls."""
    global _installed
    if _installed:
        return

    original_raw = sow_word_control._raw_docx_for_sow
    original_pdf = sow_word_control._review_pdf_for_sow

    def _raw_docx_for_sow(db: Session, sow: SOW, rev: EstimateRevision) -> bytes:
        if is_small_project_sow(db, sow):
            return (
                verify_small_project_approved_content(db, sow, rev)
                if sow.status == "APPROVED"
                else render_small_project_docx(db, sow, rev)
            )
        return original_raw(db, sow, rev)

    def _review_pdf_for_sow(db: Session, sow: SOW, rev: EstimateRevision) -> bytes:
        if is_small_project_sow(db, sow):
            # Controlled Word layout reconciliation needs the clean review PDF,
            # not the user-facing DRAFT watermark overlay.
            return render_small_project_pdf(db, sow, rev)
        return original_pdf(db, sow, rev)

    sow_word_control._raw_docx_for_sow = _raw_docx_for_sow
    sow_word_control._review_pdf_for_sow = _review_pdf_for_sow
    _installed = True

from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.pdfgen.canvas import Canvas

_installed = False


def watermark_pdf(pdf_bytes: bytes, text: str = "DRAFT") -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        overlay_buffer = io.BytesIO()
        canvas = Canvas(overlay_buffer, pagesize=(width, height))
        canvas.saveState()
        canvas.setFillColor(HexColor("#C0C0C0"))
        try:
            canvas.setFillAlpha(0.34)
        except Exception:
            pass
        canvas.setFont("Helvetica-Bold", 76)
        canvas.translate(width / 2, height / 2)
        canvas.rotate(45)
        canvas.drawCentredString(0, -24, text)
        canvas.restoreState()
        canvas.save()
        overlay = PdfReader(io.BytesIO(overlay_buffer.getvalue())).pages[0]
        page.merge_page(overlay)
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def install_sow_review_pdf_watermark() -> None:
    global _installed
    if _installed:
        return

    from . import sow_routes
    from .cip_sow import routes as cip_routes

    original_mep_pdf = sow_routes.render_pdf
    original_cip_pdf = cip_routes.render_cip_pdf

    def render_mep_review_pdf(db, sow, rev):
        content = original_mep_pdf(db, sow, rev)
        return content if sow.status == "APPROVED" else watermark_pdf(content)

    def render_cip_review_pdf(db, sow, rev):
        content = original_cip_pdf(db, sow, rev)
        return content if sow.status == "APPROVED" else watermark_pdf(content)

    sow_routes.render_pdf = render_mep_review_pdf
    cip_routes.render_cip_pdf = render_cip_review_pdf
    _installed = True

from __future__ import annotations

import html

from docx.oxml.ns import qn
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph as RP, Spacer, Table, TableStyle


SIGNATURE_MARKER = "By execution, signer certifies"
SIGNATURE_DATE_MARKER = "Accepted and Effective on"


def is_signature_table(table) -> bool:
    """Return True for the two-party signature table supplied in the MEP/CIP SOW templates."""
    try:
        text = "\n".join(cell.text for row in table.rows for cell in row.cells)
    except Exception:
        return False
    return SIGNATURE_MARKER in text and SIGNATURE_DATE_MARKER in text


def compact_signature_spacing(doc) -> int:
    """Keep the source signature block immediately below Section 8.

    The supplied customer templates contain three empty body paragraphs immediately before the
    signature table. In the controlled layout those paragraphs are sufficient to push the whole
    signature table to the next page. Removing only those trailing empty paragraphs preserves the
    source two-column signature design and keeps it on the Terms and Conditions page.
    """
    table = next((t for t in doc.tables if is_signature_table(t)), None)
    if table is None:
        return 0

    body = doc._element.body
    children = list(body)
    try:
        index = children.index(table._tbl)
    except ValueError:
        return 0

    removed = 0
    for element in reversed(children[:index]):
        if removed >= 3 or element.tag != qn("w:p"):
            break
        text = "".join(node.text or "" for node in element.findall(".//" + qn("w:t"))).strip()
        if text:
            break
        body.remove(element)
        removed += 1
    return removed


def _ensure_signature_styles(styles) -> None:
    try:
        styles["SigBody"]
    except KeyError:
        styles.add(ParagraphStyle(
            "SigBody", parent=styles["BodyS"], fontName="Helvetica", fontSize=8.4,
            leading=10.3, spaceAfter=0,
        ))
        styles.add(ParagraphStyle(
            "SigLine", parent=styles["BodyS"], fontName="Helvetica", fontSize=8.4,
            leading=10, spaceAfter=0,
        ))
        styles.add(ParagraphStyle(
            "SigNote", parent=styles["BodyS"], fontName="Helvetica", fontSize=7.3,
            leading=8.5, alignment=TA_CENTER, spaceAfter=0,
        ))


def _line_cell(label: str, width: float, styles, note: str | None = None):
    label_width = min(max(len(label) * 4.1 + 5, 18), width * 0.55)
    line_width = width - label_width
    first = Table(
        [[RP(html.escape(label), styles["SigLine"]), ""]],
        colWidths=[label_width, line_width],
        rowHeights=[12],
    )
    first.setStyle(TableStyle([
        ("LINEBELOW", (1, 0), (1, 0), .7, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    items = [first]
    if note:
        second = Table(
            [["", RP(html.escape(note), styles["SigNote"])]],
            colWidths=[label_width, line_width],
            rowHeights=[10],
        )
        second.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        items.append(second)
    return items


def signature_pdf_flowables(customer: str, styles):
    """Return the source-template two-column signature block for the review PDF."""
    _ensure_signature_styles(styles)
    column_width = 3.18 * inch
    gap_width = .22 * inch
    blank = Spacer(1, 1)

    left_intro = RP(
        "By execution, signer certifies that signer is authorized to accept and execute this SOW "
        "on behalf of Cloud Inventory®.",
        styles["SigBody"],
    )
    right_intro = RP(
        "By execution, signer certifies that signer is authorized to accept and execute this SOW "
        "on behalf of Customer.",
        styles["SigBody"],
    )
    company = RP(
        "<b>DATA SYSTEMS INTERNATIONAL, INC. DBA CLOUD INVENTORY®</b>",
        styles["SigBody"],
    )
    customer_name = RP(f"<b>{html.escape(customer)}</b>", styles["SigBody"])

    data = [
        [left_intro, blank, right_intro],
        [Spacer(1, 16), blank, Spacer(1, 16)],
        [company, blank, customer_name],
        [Spacer(1, 18), blank, Spacer(1, 18)],
        [_line_cell("By:", column_width, styles, "(Authorized Signature)"), blank,
         _line_cell("By:", column_width, styles, "(Authorized Signature)")],
        [Spacer(1, 13), blank, Spacer(1, 13)],
        [_line_cell("Print Name:", column_width, styles), blank,
         _line_cell("Print Name:", column_width, styles)],
        [Spacer(1, 7), blank, Spacer(1, 7)],
        [_line_cell("Title:", column_width, styles), blank,
         _line_cell("Title:", column_width, styles)],
        [Spacer(1, 7), blank, Spacer(1, 7)],
        [_line_cell("Accepted and Effective on:", column_width, styles, "(Date)"), blank,
         _line_cell("Accepted on:", column_width, styles, "(Date)")],
        [Spacer(1, 13), blank, Spacer(1, 13)],
        [Spacer(1, 1), blank, _line_cell("PO # (if applicable):", column_width, styles)],
    ]
    table = Table(data, colWidths=[column_width, gap_width, column_width], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [Spacer(1, 12), table, Spacer(1, 5)]

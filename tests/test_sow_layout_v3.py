from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.sow_models import SOWTemplateVersion, SOW_TEMPLATE_MEP_NET_NEW
from app.sow_layout_v3 import V3_FILENAME
from app.sow_pdf_v3 import _review_pdf


def test_controlled_sow_v3_is_active_and_uses_required_heading_numbering():
    with TestClient(app):
        with SessionLocal() as db:
            tmpl = (
                db.query(SOWTemplateVersion)
                .filter(
                    SOWTemplateVersion.template_key == SOW_TEMPLATE_MEP_NET_NEW,
                    SOWTemplateVersion.status == 'ACTIVE',
                )
                .order_by(SOWTemplateVersion.version_no.desc())
                .first()
            )
            assert tmpl is not None
            assert tmpl.version_no == 3
            assert tmpl.filename == V3_FILENAME
            content = tmpl.content

    doc = Document(BytesIO(content))
    num_pr = doc.styles['Heading 1']._element.find('.//' + qn('w:numPr'))
    assert num_pr is not None
    num_id = num_pr.find(qn('w:numId')).get(qn('w:val'))
    root = doc.part.numbering_part.element
    num = next(x for x in root.findall(qn('w:num')) if x.get(qn('w:numId')) == num_id)
    abstract_id = num.find(qn('w:abstractNumId')).get(qn('w:val'))
    abstract = next(x for x in root.findall(qn('w:abstractNum')) if x.get(qn('w:abstractNumId')) == abstract_id)
    formats = {
        int(level.get(qn('w:ilvl'))): level.find(qn('w:lvlText')).get(qn('w:val'))
        for level in abstract.findall(qn('w:lvl'))
        if int(level.get(qn('w:ilvl'))) <= 2
    }
    assert formats == {0: '%1.0', 1: '%1.%2', 2: '%1.%2.%3'}
    assert doc.styles['Heading 1'].paragraph_format.page_break_before is True
    assert doc.styles['Heading 1'].paragraph_format.keep_with_next is True
    assert doc.styles['Heading 2'].paragraph_format.keep_with_next is True
    assert doc.styles['Heading 3'].paragraph_format.keep_with_next is True
    for paragraph in doc.paragraphs:
        if paragraph.style and paragraph.style.name in ('Heading 1', 'Heading 2', 'Heading 3'):
            assert paragraph._p.pPr is None or paragraph._p.pPr.find(qn('w:numPr')) is None

    pdf = _review_pdf(content, 'Layout Test Customer', '202608999', 'August 18, 2026')
    assert pdf.startswith(b'%PDF')
    assert len(pdf) > 10_000

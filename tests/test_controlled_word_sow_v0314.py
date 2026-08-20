from __future__ import annotations

import io
import zipfile
from pathlib import Path

from docx import Document
from lxml import etree

from app.sow_word_control import NS, W_NS, apply_word_controls


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _source_docx() -> bytes:
    doc = Document()
    doc.add_heading("Statement Of Work", 0)
    doc.add_paragraph("Controlled commercial wording")
    doc.sections[0].header.paragraphs[0].text = "Cloud Inventory"
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _settings(content: bytes):
    with zipfile.ZipFile(io.BytesIO(content), "r") as z:
        return etree.fromstring(z.read("word/settings.xml"))


def test_draft_word_is_watermarked_and_track_changes_is_password_enforced():
    password = "Controlled-Test-Password-123!"
    content = apply_word_controls(_source_docx(), draft=True, password=password)

    root = _settings(content)
    track = root.find("w:trackRevisions", namespaces=NS)
    protection = root.find("w:documentProtection", namespaces=NS)
    assert track is not None
    assert protection is not None
    assert protection.get(_w("edit")) == "trackedChanges"
    assert protection.get(_w("enforcement")) == "1"
    assert protection.get(_w("algorithmName")) == "SHA-512"
    assert protection.get(_w("spinCount")) == "100000"
    assert protection.get(_w("hashValue"))
    assert protection.get(_w("saltValue"))
    assert password.encode("utf-8") not in content

    with zipfile.ZipFile(io.BytesIO(content), "r") as z:
        headers = [z.read(name) for name in z.namelist() if name.startswith("word/header")]
    assert headers
    assert all(b"CloudInventoryDraftWatermark" in raw for raw in headers)
    assert all(b"DRAFT" in raw for raw in headers)


def test_approved_word_remains_track_changes_protected_without_draft_watermark():
    content = apply_word_controls(
        _source_docx(), draft=False, password="Approved-Control-Password-456!"
    )

    root = _settings(content)
    protection = root.find("w:documentProtection", namespaces=NS)
    assert root.find("w:trackRevisions", namespaces=NS) is not None
    assert protection is not None
    assert protection.get(_w("edit")) == "trackedChanges"
    assert protection.get(_w("enforcement")) == "1"

    with zipfile.ZipFile(io.BytesIO(content), "r") as z:
        headers = [z.read(name) for name in z.namelist() if name.startswith("word/header")]
    assert headers
    assert all(b"CloudInventoryDraftWatermark" not in raw for raw in headers)


def test_controlled_word_release_is_wired_and_fail_closed_secret_is_declared():
    run = Path("app/run.py").read_text(encoding="utf-8")
    base = Path("app/templates/base.html").read_text(encoding="utf-8")
    render = Path("render.yaml").read_text(encoding="utf-8")
    control = Path("app/sow_word_control.py").read_text(encoding="utf-8")

    assert 'app.version = "0.3.14"' in run
    assert "register_controlled_sow_word(app, core)" in run
    assert "Draft Word SOW" in base
    assert "Controlled Word SOW" in base
    assert "SOW_TRACK_CHANGES_PASSWORD" in render
    assert "sync: false" in render
    assert "Controlled Word download is unavailable because" in control
    assert "MEP_NET_NEW" in control
    assert "SOW_TEMPLATE_CIP_NET_NEW" in control
    assert "small_project" not in control.casefold()

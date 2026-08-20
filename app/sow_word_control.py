from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import secrets
import zipfile

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from lxml import etree
from sqlalchemy.orm import Session

from .cip_domain import _take_route
from .cip_models import PRODUCT_CIP, PRODUCT_MEP
from .database import get_db
from .models import EstimateRevision
from .services.audit import record
from .sow_models import SOW, SOWTemplateVersion
from . import sow_service
from .cip_sow.docx import render_cip_docx, verify_cip_approved_content
from .cip_sow.core import SOW_TEMPLATE_CIP_NET_NEW

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
V_NS = "urn:schemas-microsoft-com:vml"
O_NS = "urn:schemas-microsoft-com:office:office"

NS = {"w": W_NS, "v": V_NS, "o": O_NS}
WORD_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TRACK_PASSWORD_ENV = "SOW_TRACK_CHANGES_PASSWORD"
SPIN_COUNT = 100_000


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _v(tag: str) -> str:
    return f"{{{V_NS}}}{tag}"


def _o(tag: str) -> str:
    return f"{{{O_NS}}}{tag}"


def _xml(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")


def _password_verifier(password: str, *, spin_count: int = SPIN_COUNT) -> tuple[str, str]:
    """Generate an ISO OOXML SHA-512 password verifier without storing clear text."""
    if not password:
        raise ValueError("A non-empty Track Changes password is required.")
    salt = secrets.token_bytes(16)
    value = hashlib.sha512(salt + password.encode("utf-16le")).digest()
    for index in range(spin_count):
        value = hashlib.sha512(value + index.to_bytes(4, byteorder="little")).digest()
    return base64.b64encode(value).decode("ascii"), base64.b64encode(salt).decode("ascii")


def _watermark_paragraph(text: str = "DRAFT") -> etree._Element:
    p = etree.Element(_w("p"))
    r = etree.SubElement(p, _w("r"))
    pict = etree.SubElement(r, _w("pict"))
    shape = etree.SubElement(
        pict,
        _v("shape"),
        {
            "id": "CloudInventoryDraftWatermark",
            _o("spid"): "_x0000_s1025",
            "type": "#_x0000_t136",
            "style": (
                "position:absolute;"
                "margin-left:0;margin-top:0;"
                "width:468pt;height:468pt;"
                "rotation:315;"
                "z-index:-251654144;"
                "mso-position-horizontal:center;"
                "mso-position-vertical:center;"
                "mso-wrap-edited:f;"
            ),
            "fillcolor": "#C0C0C0",
            "stroked": "f",
        },
    )
    etree.SubElement(shape, _v("fill"), {"opacity": "0.15"})
    etree.SubElement(
        shape,
        _v("textpath"),
        {"style": 'font-family:"Calibri";font-size:1pt', "string": text},
    )
    etree.SubElement(shape, _v("path"), {"textpathok": "t"})
    return p


def _settings_with_protection(settings_xml: bytes, password: str) -> bytes:
    root = etree.fromstring(settings_xml)

    for node in root.findall("w:trackRevisions", namespaces=NS):
        root.remove(node)
    root.insert(0, etree.Element(_w("trackRevisions")))

    for node in root.findall("w:documentProtection", namespaces=NS):
        root.remove(node)

    hash_value, salt_value = _password_verifier(password)
    protection = etree.Element(
        _w("documentProtection"),
        {
            _w("edit"): "trackedChanges",
            _w("enforcement"): "1",
            _w("algorithmName"): "SHA-512",
            _w("hashValue"): hash_value,
            _w("saltValue"): salt_value,
            _w("spinCount"): str(SPIN_COUNT),
        },
    )
    root.insert(1 if len(root) else 0, protection)
    return _xml(root)


def _patch_headers_with_watermark(headers: dict[str, bytes]) -> dict[str, bytes]:
    patched: dict[str, bytes] = {}
    for name, raw in headers.items():
        root = etree.fromstring(raw)
        for shape in root.xpath(
            ".//v:shape[@id='CloudInventoryDraftWatermark']", namespaces=NS
        ):
            parent = shape.getparent()
            while parent is not None and parent.tag != _w("p"):
                parent = parent.getparent()
            if parent is not None and parent.getparent() is not None:
                parent.getparent().remove(parent)
        root.append(_watermark_paragraph())
        patched[name] = _xml(root)
    return patched


def apply_word_controls(docx_bytes: bytes, *, draft: bool, password: str) -> bytes:
    """Apply mandatory protected Track Changes and, for review copies, a DRAFT watermark."""
    source = io.BytesIO(docx_bytes)
    output = io.BytesIO()

    try:
        zin = zipfile.ZipFile(source, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("The generated SOW is not a valid Word .docx document.") from exc

    with zin:
        names = zin.namelist()
        if "word/settings.xml" not in names:
            raise ValueError("The Word document does not contain word/settings.xml.")

        overrides: dict[str, bytes] = {
            "word/settings.xml": _settings_with_protection(
                zin.read("word/settings.xml"), password
            )
        }

        if draft:
            header_names = [
                name for name in names if re.fullmatch(r"word/header\d+\.xml", name)
            ]
            if not header_names:
                raise ValueError(
                    "The Word document does not contain a header for the DRAFT watermark."
                )
            overrides.update(
                _patch_headers_with_watermark(
                    {name: zin.read(name) for name in header_names}
                )
            )

        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                name = info.filename
                zout.writestr(info, overrides.get(name, zin.read(name)))

    controlled = output.getvalue()

    # Fail closed: validate the controls before any file is returned to the user.
    with zipfile.ZipFile(io.BytesIO(controlled), "r") as z:
        settings = etree.fromstring(z.read("word/settings.xml"))
        protection = settings.find("w:documentProtection", namespaces=NS)
        track = settings.find("w:trackRevisions", namespaces=NS)
        if (
            protection is None
            or track is None
            or protection.get(_w("edit")) != "trackedChanges"
            or protection.get(_w("enforcement")) != "1"
            or protection.get(_w("algorithmName")) != "SHA-512"
            or not protection.get(_w("hashValue"))
            or not protection.get(_w("saltValue"))
        ):
            raise ValueError("Controlled Word protection could not be verified.")
        if draft:
            headers = [
                z.read(name)
                for name in z.namelist()
                if re.fullmatch(r"word/header\d+\.xml", name)
            ]
            if not headers or not all(
                b"CloudInventoryDraftWatermark" in raw for raw in headers
            ):
                raise ValueError("DRAFT watermark could not be verified.")

    if password.encode("utf-8") in controlled:
        raise ValueError("Controlled Word protection failed because clear-text secret data was detected.")
    return controlled


def _raw_docx_for_sow(db: Session, sow: SOW, rev: EstimateRevision) -> bytes:
    template = db.get(SOWTemplateVersion, sow.template_version_id)
    if not template:
        raise ValueError("The SOW template version no longer exists.")

    if template.template_key == "MEP_NET_NEW":
        return (
            sow_service.verify_approved_content(db, sow, rev)
            if sow.status == "APPROVED"
            else sow_service.render_docx(db, sow, rev)
        )
    if template.template_key == SOW_TEMPLATE_CIP_NET_NEW:
        return (
            verify_cip_approved_content(db, sow, rev)
            if sow.status == "APPROVED"
            else render_cip_docx(db, sow, rev)
        )
    raise ValueError("Controlled Word download is not available for this SOW template family.")


def _word_filename(sow: SOW, rev: EstimateRevision, product: str) -> str:
    status_suffix = "" if sow.status == "APPROVED" else "-DRAFT"
    product_segment = "CIP" if product == PRODUCT_CIP else "MEP"
    return (
        f"{rev.estimate.estimate_number}-{product_segment}-SOW-"
        f"R{sow.sow_revision_no}{status_suffix}.docx"
    )


def register_controlled_sow_word(app, core) -> None:
    # Replace the legacy approved-only route. Every Word SOW leaves through this boundary.
    _take_route(app, "/sow/{sid}/docx", "GET")

    @app.get("/sow/{sid}/docx")
    def controlled_sow_docx(
        sid: int,
        request: Request,
        db: Session = Depends(get_db),
    ):
        user = core.current_user(request, db)
        sow = db.get(SOW, sid)
        if not sow:
            raise HTTPException(404, "SOW not found")
        rev = db.get(EstimateRevision, sow.estimate_revision_id)
        if not rev:
            raise HTTPException(404, "Estimate revision not found")

        password = os.getenv(TRACK_PASSWORD_ENV, "").strip()
        if not password:
            raise HTTPException(
                503,
                "Controlled Word download is unavailable because "
                "SOW_TRACK_CHANGES_PASSWORD is not configured.",
            )

        try:
            raw = _raw_docx_for_sow(db, sow, rev)
            content = apply_word_controls(
                raw,
                draft=sow.status != "APPROVED",
                password=password,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

        event_type = (
            "SOW_APPROVED_DOCX_GENERATED"
            if sow.status == "APPROVED"
            else "SOW_DRAFT_DOCX_GENERATED"
        )
        product = (
            PRODUCT_CIP
            if (rev.engine_version or "").upper().startswith("CIP-")
            else PRODUCT_MEP
        )
        record(
            db,
            event_type=event_type,
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            field_name=f"SOW:{sow.id}",
            new_value=(
                f"Template {sow.template_version_id}; "
                f"content {sow.content_hash or 'unapproved'}"
            ),
        )
        db.commit()

        return Response(
            content,
            media_type=WORD_MIME,
            headers={
                "Content-Disposition":
                    f'attachment; filename="{_word_filename(sow, rev, product)}"'
            },
        )

from __future__ import annotations

import base64
from datetime import datetime

from sqlalchemy.orm import Session

from . import sow_layout_v2, sow_layout_v3, sow_service
from .cip_models import PRODUCT_MEP
from .models import User
from .services.audit import record
from .sow_models import SOWTemplateVersion, SOW_TEMPLATE_MEP_NET_NEW

_PREVIOUS_SEED = sow_service.seed_initial_sow_template


def _bundled_v1_content() -> bytes | None:
    parts = sorted(sow_service.INITIAL_TEMPLATE_DIR.glob(sow_service.INITIAL_TEMPLATE_PART_GLOB))
    if not parts:
        return None
    encoded = "".join(part.read_text() for part in parts)
    return base64.b64decode(encoded.strip())


def _content_matches(row: SOWTemplateVersion, content: bytes) -> bool:
    expected = sow_service.sha256_bytes(content)
    return row.content_sha256 == expected or row.content == content


def _is_controlled_v2(row: SOWTemplateVersion, expected_content: bytes) -> bool:
    return (
        _content_matches(row, expected_content)
        or (row.filename == sow_layout_v2.V2_FILENAME and row.change_reason == sow_layout_v2.V2_REASON)
    )


def _is_controlled_v3(row: SOWTemplateVersion, expected_content: bytes) -> bool:
    return (
        _content_matches(row, expected_content)
        or (row.filename == sow_layout_v3.V3_FILENAME and row.change_reason == sow_layout_v3.V3_REASON)
    )


def _new_template_row(*, version_no: int, filename: str, content: bytes, reason: str, admin: User,
                      status: str, activated_at=None) -> SOWTemplateVersion:
    return SOWTemplateVersion(
        template_key=SOW_TEMPLATE_MEP_NET_NEW,
        label="MEP New Client SOW",
        product_type=PRODUCT_MEP,
        customer_type="Net_New",
        version_no=version_no,
        status=status,
        filename=filename,
        content=content,
        content_sha256=sow_service.sha256_bytes(content),
        change_reason=reason,
        created_by=admin.id,
        activated_by=admin.id if status == "ACTIVE" else None,
        activated_at=activated_at if status == "ACTIVE" else None,
    )


def reconcile_controlled_sow_template(db: Session) -> None:
    """Safely advance an untouched bundled v1 database to the current controlled v3 template.

    Historical SOW bindings are never changed. If the active template contains administrator-modified
    DOCX content, this routine deliberately does nothing and leaves template activation to the admin UI.
    """
    _PREVIOUS_SEED(db)

    rows = (
        db.query(SOWTemplateVersion)
        .filter(SOWTemplateVersion.template_key == SOW_TEMPLATE_MEP_NET_NEW)
        .order_by(SOWTemplateVersion.version_no)
        .all()
    )
    if not rows:
        return

    active_rows = [row for row in rows if row.status == "ACTIVE"]
    active = max(active_rows, key=lambda row: row.version_no) if active_rows else None
    if active and active.version_no > 3:
        return

    bundled_v1 = _bundled_v1_content()
    v1 = next((row for row in rows if row.version_no == 1), None)
    if bundled_v1 is None or v1 is None or not _content_matches(v1, bundled_v1):
        return

    expected_v2 = sow_layout_v2._build_v2_content(v1.content)
    expected_v3 = sow_layout_v3._build_v3_content(expected_v2)

    v2 = next((row for row in rows if row.version_no == 2), None)
    v3 = next((row for row in rows if row.version_no == 3), None)

    # Never overwrite an administrator-created version occupying a controlled version number.
    # v2/v3 are generated DOCX ZIP packages, so immutable controlled metadata is accepted in
    # addition to a byte-identical hash match.
    if v2 is not None and not _is_controlled_v2(v2, expected_v2):
        return
    if v3 is not None and not _is_controlled_v3(v3, expected_v3):
        return
    if active is not None and active.version_no == 2 and v2 is None:
        return
    if active is not None and active.version_no == 3 and v3 is None:
        return

    admin = db.query(User).filter(User.username_normalized == "admin").first()
    if not admin:
        return

    now = datetime.utcnow()
    if v2 is None:
        v2 = _new_template_row(
            version_no=2,
            filename=sow_layout_v2.V2_FILENAME,
            content=expected_v2,
            reason=sow_layout_v2.V2_REASON,
            admin=admin,
            status="RETIRED",
        )
        db.add(v2)
        db.flush()
        record(
            db,
            event_type="SOW_TEMPLATE_CREATED",
            user_id=admin.id,
            field_name=f"SOW_TEMPLATE:{SOW_TEMPLATE_MEP_NET_NEW}:2",
            new_value=v2.filename,
            reason="Controlled template recovery created historical v2.",
        )

    if v3 is None:
        v3 = _new_template_row(
            version_no=3,
            filename=sow_layout_v3.V3_FILENAME,
            content=expected_v3,
            reason=sow_layout_v3.V3_REASON,
            admin=admin,
            status="ACTIVE",
            activated_at=now,
        )
        db.add(v3)
        db.flush()
        record(
            db,
            event_type="SOW_TEMPLATE_ACTIVATED",
            user_id=admin.id,
            field_name=f"SOW_TEMPLATE:{SOW_TEMPLATE_MEP_NET_NEW}:3",
            new_value=v3.filename,
            reason="Controlled template recovery activated current v3.",
        )
    elif v3.status != "ACTIVE":
        old = v3.status
        v3.status = "ACTIVE"
        v3.activated_by = admin.id
        v3.activated_at = now
        v3.retired_at = None
        record(
            db,
            event_type="SOW_TEMPLATE_ACTIVATED",
            user_id=admin.id,
            field_name=f"SOW_TEMPLATE:{SOW_TEMPLATE_MEP_NET_NEW}:3",
            old_value=old,
            new_value="ACTIVE",
            reason="Controlled template recovery activated current v3.",
        )

    for row in rows:
        if row.id == v3.id:
            continue
        if row.version_no in (1, 2) and row.status == "ACTIVE":
            old = row.status
            row.status = "RETIRED"
            row.retired_at = now
            record(
                db,
                event_type="SOW_TEMPLATE_RETIRED",
                user_id=admin.id,
                field_name=f"SOW_TEMPLATE:{SOW_TEMPLATE_MEP_NET_NEW}:{row.version_no}",
                old_value=old,
                new_value="RETIRED",
                reason="Superseded by current controlled SOW template v3.",
            )

    if v2.status == "ACTIVE":
        v2.status = "RETIRED"
        v2.retired_at = now

    db.commit()


sow_service.seed_initial_sow_template = reconcile_controlled_sow_template

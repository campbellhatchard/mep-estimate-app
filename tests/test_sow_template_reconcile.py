from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.sow_models import SOWTemplateVersion, SOW_TEMPLATE_MEP_NET_NEW
from app.sow_template_reconcile import reconcile_controlled_sow_template


def _templates(db):
    return (
        db.query(SOWTemplateVersion)
        .filter(SOWTemplateVersion.template_key == SOW_TEMPLATE_MEP_NET_NEW)
        .order_by(SOWTemplateVersion.version_no)
        .all()
    )


def test_v1_with_legacy_metadata_is_advanced_to_controlled_v3():
    with TestClient(app):
        with SessionLocal() as db:
            rows = _templates(db)
            v1 = next(row for row in rows if row.version_no == 1)
            v2 = next(row for row in rows if row.version_no == 2)
            v3 = next(row for row in rows if row.version_no == 3)

            v1.status = 'ACTIVE'
            v1.filename = 'Legacy_MEP_New_Client_Template.docx'
            v1.change_reason = 'Legacy production metadata'
            v2.status = 'RETIRED'
            v3.status = 'RETIRED'
            db.commit()

            reconcile_controlled_sow_template(db)

            db.refresh(v1); db.refresh(v2); db.refresh(v3)
            assert v1.status == 'RETIRED'
            assert v2.status == 'RETIRED'
            assert v3.status == 'ACTIVE'


def test_v1_content_differences_do_not_block_installing_current_controlled_v3():
    with TestClient(app):
        with SessionLocal() as db:
            rows = _templates(db)
            v1 = next(row for row in rows if row.version_no == 1)
            v2 = next(row for row in rows if row.version_no == 2)
            v3 = next(row for row in rows if row.version_no == 3)
            original_content = v1.content
            original_hash = v1.content_sha256

            # Reproduce the live environment symptom: v1 is the only active template and its
            # stored DOCX/hash do not match the current bundled packaging.
            v1.content = original_content + b'legacy-production-packaging'
            v1.content_sha256 = 'legacy-production-hash'
            v1.status = 'ACTIVE'
            v2.status = 'RETIRED'
            v3.status = 'RETIRED'
            db.commit()

            reconcile_controlled_sow_template(db)

            db.refresh(v1); db.refresh(v2); db.refresh(v3)
            assert v1.status == 'RETIRED'
            assert v2.status == 'RETIRED'
            assert v3.status == 'ACTIVE'

            # Restore the shared test database contents for later tests; status remains the
            # intended production state with v3 active.
            v1.content = original_content
            v1.content_sha256 = original_hash
            db.commit()

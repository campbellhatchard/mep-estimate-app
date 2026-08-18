from fastapi.testclient import TestClient

from app.run import app
from app.database import SessionLocal
from app.sow_models import SOWTemplateVersion, SOW_TEMPLATE_MEP_NET_NEW
from app.sow_template_reconcile import reconcile_controlled_sow_template


def test_original_v1_with_legacy_metadata_is_advanced_to_controlled_v3():
    with TestClient(app):
        with SessionLocal() as db:
            rows = (
                db.query(SOWTemplateVersion)
                .filter(SOWTemplateVersion.template_key == SOW_TEMPLATE_MEP_NET_NEW)
                .order_by(SOWTemplateVersion.version_no)
                .all()
            )
            v1 = next(row for row in rows if row.version_no == 1)
            v2 = next(row for row in rows if row.version_no == 2)
            v3 = next(row for row in rows if row.version_no == 3)

            # Reproduce the existing-environment failure mode: the original controlled v1
            # DOCX is still present, but legacy metadata prevents the old exact-string guard
            # from recognizing it as the bundled template.
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


def test_reconciliation_does_not_override_modified_v1_content():
    with TestClient(app):
        with SessionLocal() as db:
            rows = (
                db.query(SOWTemplateVersion)
                .filter(SOWTemplateVersion.template_key == SOW_TEMPLATE_MEP_NET_NEW)
                .order_by(SOWTemplateVersion.version_no)
                .all()
            )
            v1 = next(row for row in rows if row.version_no == 1)
            v3 = next(row for row in rows if row.version_no == 3)
            original_content = v1.content
            original_hash = v1.content_sha256

            v1.content = original_content + b'admin-change'
            v1.content_sha256 = 'modified-admin-template'
            v1.status = 'ACTIVE'
            v3.status = 'RETIRED'
            db.commit()

            reconcile_controlled_sow_template(db)
            db.refresh(v1); db.refresh(v3)
            assert v1.status == 'ACTIVE'
            assert v3.status == 'RETIRED'

            # Restore the shared test database for subsequent tests.
            v1.content = original_content
            v1.content_sha256 = original_hash
            v1.status = 'RETIRED'
            v3.status = 'ACTIVE'
            db.commit()

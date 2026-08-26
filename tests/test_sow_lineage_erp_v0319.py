from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.run import app
from app import sow_service
from app.cip_models import CIPRevisionInput
from app.cip_sow.docx import cip_content_hash_for
from app.database import SessionLocal
from app.models import AuditEvent, EstimateRevision
from app.small_project_models import SmallProjectSOWConfig
from app.small_project_workflow import (
    render_small_project_docx,
    small_project_content_hash_for,
)
from app.sow_models import SOW, SOWDevice


FAMILIES = [
    ("MEP", False),
    ("CIP", False),
    ("MEP", True),
    ("CIP", True),
]


def _login(client):
    response = client.post(
        "/login",
        data={"username": "Admin", "password": "TestPass123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _new_estimate(client, product: str) -> int:
    response = client.post(
        "/estimates/new",
        data={"product_type": product},
        follow_redirects=False,
    )
    assert response.status_code == 303, (response.status_code, response.text)
    return int(response.headers["location"].rstrip("/").rsplit("/", 1)[-1])


def _prepare_approved_estimate(rid: int, product: str, small_project: bool) -> None:
    with SessionLocal() as db:
        rev = db.get(EstimateRevision, rid)
        rev.status = "APPROVED"
        rev.customer = f"{product} {'Small' if small_project else 'Net New'} Lineage Customer"
        rev.customer_type = "Install_Base" if small_project else "Net_New"
        rev.project_type = "Small Project" if small_project else rev.project_type
        rev.go_live_sites = 0
        rev.go_live_type = "None"
        if product == "CIP":
            inp = db.get(CIPRevisionInput, rid)
            assert inp is not None
            if small_project:
                inp.project_type = "Small Project"
            inp.go_live_sites = 0
            inp.go_live_type = "None"
        db.commit()


def _hash_for_family(db, sow: SOW, rev: EstimateRevision, product: str, small_project: bool):
    if small_project:
        return small_project_content_hash_for(db, sow, rev)
    if product == "CIP":
        return cip_content_hash_for(db, sow, rev)
    return sow_service.content_hash_for(db, sow, rev)


@pytest.mark.parametrize("product,small_project", FAMILIES)
def test_new_estimate_revision_sow_carries_manual_content_within_same_family(
    product: str, small_project: bool
):
    objective = f"Carry forward manually authored {product} {'Small Project' if small_project else 'Net New'} objective."
    with TestClient(app) as client:
        _login(client)
        rid1 = _new_estimate(client, product)
        _prepare_approved_estimate(rid1, product, small_project)

        created = client.post(f"/estimate/{rid1}/sow/create", follow_redirects=False)
        assert created.status_code == 303, (created.status_code, created.text)
        sid1 = int(created.headers["location"].rstrip("/").rsplit("/", 1)[-1])

        with SessionLocal() as db:
            source = db.get(SOW, sid1)
            rev1 = db.get(EstimateRevision, rid1)
            assert source.composition_version == 2
            source.project_objective = objective
            source.invoice_frequency = "Monthly"
            source.erp_version = "9.2.8.4"
            source.erp_deployment_model = "Customer Managed / Private Cloud"
            db.add(
                SOWDevice(
                    sow_id=source.id,
                    device_type="Handheld Unit",
                    make_model="Zebra MC9400",
                    os_version="Android 13",
                    sort_order=0,
                )
            )
            if small_project:
                cfg = (
                    db.query(SmallProjectSOWConfig)
                    .filter(SmallProjectSOWConfig.sow_id == source.id)
                    .one()
                )
                cfg.key_user_training_count = 4
                target = next(row for row in cfg.deliverables if row.deliverable_key != "MEP_INSTALL")
                target.scope_description = f"Customer-authored {product} scope detail."
                target.detail_notes = "Carry this detail forward."
                method = cfg.methodologies[0]
                method.mode = "Exclude"
                if product == "MEP":
                    cfg.install_mode = "Cloud"
                    mep_install = next(row for row in cfg.deliverables if row.deliverable_key == "MEP_INSTALL")
                    mep_install.include = True
                    mep_install.scope_description = "Customer-authored MEP installation scope."
            db.flush()
            digest, text, _ = _hash_for_family(db, source, rev1, product, small_project)
            source.status = "APPROVED"
            source.content_hash = digest
            source.approved_text_snapshot = text
            db.commit()

        revised = client.post(
            f"/estimate/{rid1}/new-revision",
            data={"revision_reason": "Customer changed approved estimate scope."},
            follow_redirects=False,
        )
        assert revised.status_code == 303, (revised.status_code, revised.text)
        rid2 = int(revised.headers["location"].rstrip("/").rsplit("/", 1)[-1])
        with SessionLocal() as db:
            rev2 = db.get(EstimateRevision, rid2)
            rev2.status = "APPROVED"
            # Prove the destination remains tied to the revised estimate's current
            # commercial values rather than copying commercial state from the source SOW.
            rev2.billing_rate = 325
            rev2.calculated_hours = 17.5
            rev2.calculated_fees = 5687.5
            db.commit()

        created2 = client.post(f"/estimate/{rid2}/sow/create", follow_redirects=False)
        assert created2.status_code == 303, (created2.status_code, created2.text)
        sid2 = int(created2.headers["location"].rstrip("/").rsplit("/", 1)[-1])

        with SessionLocal() as db:
            source = db.get(SOW, sid1)
            dest = db.get(SOW, sid2)
            rev2 = db.get(EstimateRevision, rid2)
            assert source.status == "APPROVED"
            assert dest.status == "DRAFT"
            assert dest.composition_version == 2
            assert dest.project_objective == objective
            assert dest.invoice_frequency == "Monthly"
            assert dest.erp_version == "9.2.8.4"
            assert dest.erp_deployment_model == "Customer Managed / Private Cloud"
            assert [(x.device_type, x.make_model, x.os_version) for x in dest.devices] == [
                ("Handheld Unit", "Zebra MC9400", "Android 13")
            ]
            assert rev2.billing_rate == 325
            assert rev2.calculated_hours == 17.5
            assert rev2.calculated_fees == 5687.5

            if small_project:
                src_cfg = db.query(SmallProjectSOWConfig).filter(SmallProjectSOWConfig.sow_id == sid1).one()
                dst_cfg = db.query(SmallProjectSOWConfig).filter(SmallProjectSOWConfig.sow_id == sid2).one()
                assert dst_cfg.key_user_training_count == 4
                src_by_key = {row.deliverable_key: row for row in src_cfg.deliverables}
                dst_by_key = {row.deliverable_key: row for row in dst_cfg.deliverables}
                carried_key = next(key for key in src_by_key if key != "MEP_INSTALL")
                assert dst_by_key[carried_key].scope_description == src_by_key[carried_key].scope_description
                assert dst_by_key[carried_key].detail_notes == src_by_key[carried_key].detail_notes
                assert dst_cfg.methodologies[0].mode == "Exclude"
                if product == "MEP":
                    assert dst_cfg.install_mode == "Cloud"
                    assert dst_by_key["MEP_INSTALL"].include is True
                    assert dst_by_key["MEP_INSTALL"].scope_description == "Customer-authored MEP installation scope."

            event = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.revision_id == rid2,
                    AuditEvent.event_type == "SOW_CONTENT_CARRIED_FORWARD",
                )
                .one()
            )
            assert f"SOW {sid1}" in (event.old_value or "")
            assert f"SOW {sid2}" in (event.new_value or "")

            # The source remains hash-verifiable after destination creation.
            _hash_for_family(db, source, db.get(EstimateRevision, rid1), product, small_project)


def test_mep_net_new_composition_v2_adds_erp_version_but_v1_historical_does_not():
    with TestClient(app) as client:
        _login(client)
        rid = _new_estimate(client, "MEP")
        _prepare_approved_estimate(rid, "MEP", False)
        created = client.post(f"/estimate/{rid}/sow/create", follow_redirects=False)
        sid = int(created.headers["location"].rstrip("/").rsplit("/", 1)[-1])

        with SessionLocal() as db:
            sow = db.get(SOW, sid)
            rev = db.get(EstimateRevision, rid)
            sow.erp_version = "9.2.8.4"
            sow.composition_version = 2
            db.flush()
            current = sow_service.render_docx(db, sow, rev)
            current_text = sow_service.canonical_text(current)
            sentence = f"MEP will be connected to {rev.erp}, version 9.2.8.4."
            assert sentence in current_text

            sow.composition_version = 1
            db.flush()
            historical = sow_service.render_docx(db, sow, rev)
            historical_text = sow_service.canonical_text(historical)
            assert sentence not in historical_text


def test_mep_small_project_requires_and_renders_connected_erp_version():
    with TestClient(app) as client:
        _login(client)
        rid = _new_estimate(client, "MEP")
        _prepare_approved_estimate(rid, "MEP", True)
        created = client.post(f"/estimate/{rid}/sow/create", follow_redirects=False)
        assert created.status_code == 303
        sid = int(created.headers["location"].rstrip("/").rsplit("/", 1)[-1])

        page = client.get(f"/sow/{sid}")
        assert page.status_code == 200
        assert "Connected ERP / System" in page.text
        assert "ERP / System Version" in page.text

        with SessionLocal() as db:
            sow = db.get(SOW, sid)
            rev = db.get(EstimateRevision, rid)
            cfg = db.query(SmallProjectSOWConfig).filter(SmallProjectSOWConfig.sow_id == sid).one()
            cfg.install_mode = "Cloud"
            install = next(row for row in cfg.deliverables if row.deliverable_key == "MEP_INSTALL")
            install.include = True
            install.scope_description = "Provision MEP in the managed cloud."
            sow.erp_version = "9.2.8.4"
            db.commit()

        with SessionLocal() as db:
            sow = db.get(SOW, sid)
            rev = db.get(EstimateRevision, rid)
            docx = render_small_project_docx(db, sow, rev)
            text = sow_service.canonical_text(docx)
            assert "MEP Cloud Installation" in text
            assert f"MEP will be connected to {rev.erp}, version 9.2.8.4." in text

        with SessionLocal() as db:
            sow = db.get(SOW, sid)
            sow.erp_version = ""
            db.commit()
        finalized = client.post(f"/sow/{sid}/finalize", follow_redirects=False)
        assert finalized.status_code == 400
        assert "ERP / System Version is required" in finalized.text

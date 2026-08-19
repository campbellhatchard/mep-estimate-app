from fastapi.testclient import TestClient

from app.run import app
from tests.test_zzzz_cip_sow import login, create_approved_net_new_cip


def test_cip_sow_pdf_diagnostic_message():
    with TestClient(app) as client:
        login(client)
        rid = create_approved_net_new_cip(client)
        created = client.post(f"/estimate/{rid}/sow/create", follow_redirects=False)
        assert created.status_code == 303
        sid = int(created.headers["location"].rsplit("/", 1)[-1])
        review = client.get(f"/sow/{sid}/pdf")
        assert review.status_code == 200, review.text

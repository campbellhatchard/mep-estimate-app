from pathlib import Path
import inspect

from app.models import EstimateRevision
from app.cip_models import CIPRevisionInput
from app.cip_revision import create_cip_estimate


def test_mep_new_estimate_defaults_are_net_new_and_mep_cloud():
    assert EstimateRevision.__table__.c.customer_type.default.arg == "Net_New"
    assert EstimateRevision.__table__.c.project_type.default.arg == "MEP Cloud"


def test_cip_new_estimate_defaults_remain_net_new_and_cip_install():
    assert CIPRevisionInput.__table__.c.project_type.default.arg == "CIP Install"
    source = inspect.getsource(create_cip_estimate)
    assert 'customer_type="Net_New"' in source
    assert 'project_type="CIP Install"' in source


def test_billing_rate_is_formatted_to_two_decimal_places_in_both_estimators():
    script = Path("app/static/precision_ui.js").read_text(encoding="utf-8")
    assert 'input[name="billing_rate"]' in script
    assert "billingRate.value = value.toFixed(2)" in script

from __future__ import annotations

from . import main as core
from .application_bootstrap import configure_application


app = core.app
configure_application(app, core)

# CIP-1.0.2 is a controlled commercial-rule correction: Investment Hours are a
# funding allocation inside gross Task Hours, not additional effort. Install it
# after the baseline application bootstrap so every already-imported CIP route and
# schedule module uses the same current editable engine while locked historical
# revisions continue to dispatch through the versioned engine boundary.
from .services.cip_calculation_v102 import (  # noqa: E402
    CIP_ENGINE_VERSION as CIP_FUNDING_ENGINE_VERSION,
    calculation as cip_funding_calculation,
    recalculate_and_store as cip_funding_recalculate,
)
from .services import cip_calculation as cip_public_module, cip_schedule as cip_schedule_module  # noqa: E402
from . import cip_domain, cip_revision, cip_routes_detail, cip_routes_estimate, cip_routes_exports  # noqa: E402

cip_public_module.calculation = cip_funding_calculation
cip_public_module.recalculate_and_store = cip_funding_recalculate
cip_public_module.CIP_ENGINE_VERSION = CIP_FUNDING_ENGINE_VERSION
cip_schedule_module.calculation = cip_funding_calculation
cip_domain.cip_calculation = cip_funding_calculation
cip_domain.cip_recalculate_and_store = cip_funding_recalculate
cip_revision.cip_recalculate_and_store = cip_funding_recalculate
cip_revision.CIP_ENGINE_VERSION = CIP_FUNDING_ENGINE_VERSION
cip_routes_estimate.cip_recalculate_and_store = cip_funding_recalculate
cip_routes_detail.cip_calculation = cip_funding_calculation
cip_routes_detail.cip_recalculate_and_store = cip_funding_recalculate
cip_routes_exports.cip_calculation = cip_funding_calculation

__all__ = ["app"]

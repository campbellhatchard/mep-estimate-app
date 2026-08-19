from __future__ import annotations

from . import main as core
from .enhancements import configure_templates, register_routes, clean_schedule_tasks, ROLE_LABELS
from .models import ROLE_ORDER
from .estimate_numbering import register_numbered_estimate_route
from .cip import register_cip
from .revision_history import register_revision_history
from .assumptions import register_assumption_routes
# Apply controlled SOW layout migrations before SOW registration.
from . import sow_layout_v2  # noqa: F401
from . import sow_layout_v3  # noqa: F401
from . import sow_template_reconcile  # noqa: F401
from .sow_template_startup import register_sow_template_reconciliation
from .sow_routes import register_sow
from .cip_sow import register_cip_sow

if "SOW_APPROVER" not in ROLE_ORDER:
    ROLE_ORDER.insert(ROLE_ORDER.index("READ_ONLY"), "SOW_APPROVER")
ROLE_LABELS["SOW_APPROVER"] = "SOW Approver"

app = core.app
app.title = "Cloud Inventory Services Estimator"
app.version = "0.3.7"

configure_templates(core.templates)
register_routes(app)
register_numbered_estimate_route(app, core)

# Preserve the locked MEP schedule behavior and terminology cleanup. CIP registration
# receives this exact callable and dispatches only CIP revisions to the CIP schedule generator.
_original_generate_schedule = core.generate_schedule


def _generate_schedule_with_normalized_text(db, rev, replace=True):
    tasks = _original_generate_schedule(db, rev, replace=replace)
    return clean_schedule_tasks(tasks)


core.generate_schedule = _generate_schedule_with_normalized_text
register_cip(app, core, core.generate_schedule)
# Register revision lifecycle last so the same controlled behavior applies to both products.
register_revision_history(app, core)
register_assumption_routes(app, core)
# Explicitly reconcile the controlled MEP SOW templates at process startup. register_sow also
# retains its existing seed hook; this direct registration removes any import-binding ambiguity.
register_sow_template_reconciliation(app)
register_sow(app, core)
# CIP SOW is layered after the accepted MEP SOW so shared workflow routes remain unchanged
# and only product-specific SOW entry/render/finalization behavior is dispatched for CIP.
register_cip_sow(app, core)

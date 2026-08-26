from __future__ import annotations

from . import main as core
from .enhancements import configure_templates, register_routes, clean_schedule_tasks, ROLE_LABELS
from .models import ROLE_ORDER
from .estimate_numbering import register_numbered_estimate_route
from .cip import register_cip
from .revision_history import register_revision_history
from .assumptions import register_assumption_routes
from .estimate_delete import register_estimate_delete
from .detail_preview import register_detail_preview
from .precision_runtime import install_calculation_precision, register_precision_routes, register_precision_startup
# Apply controlled SOW layout migrations before SOW registration.
from . import sow_layout_v2  # noqa: F401
from . import sow_layout_v3  # noqa: F401
from . import sow_template_reconcile  # noqa: F401
from .sow_template_startup import register_sow_template_reconciliation
from .sow_routes import register_sow
from .cip_sow import register_cip_sow
from .sow_word_control import register_controlled_sow_word
from .sow_signature_runtime import install_sow_signature_layout
from .sow_review_runtime import install_sow_review_pdf_watermark
from . import small_project_models  # noqa: F401
from .small_project_sow import register_small_project_sow_templates
from .small_project_template_admin import register_small_project_template_admin
from .small_project_workflow import register_small_project_sow_workflow
from .small_project_word_runtime import install_small_project_word_dispatch

if "SOW_APPROVER" not in ROLE_ORDER:
    ROLE_ORDER.insert(ROLE_ORDER.index("READ_ONLY"), "SOW_APPROVER")
ROLE_LABELS["SOW_APPROVER"] = "SOW Approver"

app = core.app
app.title = "Cloud Inventory Services Estimator"
app.version = "0.3.16.0"

configure_templates(core.templates)
# Replace calculation references before any product routes capture them. Locked revisions
# continue to dispatch to their historical engine; editable/new revisions use v1.0.1.
install_calculation_precision(core)
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
# Product dispatch now exists; add calculation and detail previews using the same corrected
# calculation engine as Save so unsaved changes produce production-equivalent results.
register_precision_routes(app, core)
register_detail_preview(app, core)
register_precision_startup(app)
# Register revision lifecycle last so the same controlled behavior applies to both products.
register_revision_history(app, core)
register_assumption_routes(app, core)
# Draft estimate deletion is shared by MEP and CIP and remains unavailable once a controlled
# historical revision exists.
register_estimate_delete(app, core)
# Install the source-template two-column signature layout before SOW routes are registered.
# This affects both review PDFs and generated Word documents without changing commercial content.
install_sow_signature_layout()
# Non-approved SOW review PDFs remain visibly controlled until the approval event is complete.
install_sow_review_pdf_watermark()
# Explicitly reconcile the controlled MEP SOW templates at process startup. register_sow also
# retains its existing seed hook; this direct registration removes any import-binding ambiguity.
register_sow_template_reconciliation(app)
register_sow(app, core)
# CIP SOW is layered after the accepted MEP SOW so shared workflow routes remain unchanged
# and only product-specific SOW entry/render/finalization behavior is dispatched for CIP.
register_cip_sow(app, core)
# Four controlled template families and the normalized Small Project authoring model.
register_small_project_template_admin(app, core)
register_small_project_sow_templates(app)
# Small Project dispatch is layered after both accepted Net New product routes. It intercepts
# only pinned MEP_SMALL_PROJECT / CIP_SMALL_PROJECT SOWs and delegates every other route.
register_small_project_sow_workflow(app, core)
# Extend, rather than replace, the accepted controlled Word boundary for Small Project families.
install_small_project_word_dispatch()
# All Microsoft Word SOW downloads leave through one protected boundary. Register last so
# MEP/CIP Net New and Small Project families share the same control enforcement.
register_controlled_sow_word(app, core)

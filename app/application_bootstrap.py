from __future__ import annotations

from .assumptions import register_assumption_routes
from .calculation_explain import install_calculation_explanations
from .cip import register_cip
from .detail_preview import register_detail_preview
from .enhancements import ROLE_LABELS, clean_schedule_tasks, configure_templates, register_routes
from .estimate_delete import register_estimate_delete
from .estimate_numbering import register_numbered_estimate_route
from .estimate_revision_controls import (
    install_estimate_business_rule_controls,
    register_revision_rationale_controls,
)
from .mep_sow_erp_runtime import install_mep_sow_erp_wording
from .models import ROLE_ORDER
from .precision_runtime import (
    install_calculation_precision,
    register_precision_routes,
    register_precision_startup,
)
from .revision_history import register_revision_history
from .route_architecture import assert_final_route_owners
from .schedule_exports_runtime import register_schedule_exports
from .small_project_sow import register_small_project_sow_templates
from .small_project_template_admin import register_small_project_template_admin
from .small_project_word_runtime import install_small_project_word_dispatch
from .small_project_workflow import register_small_project_sow_workflow
from .sow_lineage_runtime import register_sow_lineage_carry_forward
from .sow_review_runtime import install_sow_review_pdf_watermark
from .sow_routes import register_sow
from .sow_signature_runtime import install_sow_signature_layout
from .sow_template_startup import register_sow_template_reconciliation
from .sow_word_control import register_controlled_sow_word
from .cip_sow import register_cip_sow
from .tools_admin_runtime import register_tools_admin_runtime
from .warning_hardening import install_warning_hardening

# Model/table registration and controlled template migrations are import-time compatibility
# boundaries. Keep them explicit here rather than scattering side-effect imports in run.py.
from . import small_project_models  # noqa: F401
from . import sow_layout_v2  # noqa: F401
from . import sow_layout_v3  # noqa: F401
from . import sow_template_reconcile  # noqa: F401


RELEASE_VERSION = "0.3.23.0"


def _configure_roles() -> None:
    if "TOOLS_ADMIN" not in ROLE_ORDER:
        ROLE_ORDER.insert(ROLE_ORDER.index("ESTIMATOR"), "TOOLS_ADMIN")
    ROLE_LABELS["TOOLS_ADMIN"] = "Tools Admin"

    if "SOW_APPROVER" not in ROLE_ORDER:
        ROLE_ORDER.insert(ROLE_ORDER.index("READ_ONLY"), "SOW_APPROVER")
    ROLE_LABELS["SOW_APPROVER"] = "SOW Approver"


def _install_schedule_dispatch(core) -> None:
    """Preserve locked MEP schedule behavior while exposing one product-aware generator."""

    original_generate_schedule = core.generate_schedule

    def generate_schedule_with_normalized_text(db, rev, replace=True):
        tasks = original_generate_schedule(db, rev, replace=replace)
        return clean_schedule_tasks(tasks)

    core.generate_schedule = generate_schedule_with_normalized_text
    register_cip(core.app, core, core.generate_schedule)


def _register_estimate_capabilities(app, core) -> None:
    # Calculation/validation bindings must be installed before legacy route closures capture
    # them. Locked revisions continue to dispatch to their historical engine versions.
    install_calculation_precision(core)
    install_estimate_business_rule_controls(core)

    register_routes(app)
    register_numbered_estimate_route(app, core)
    _install_schedule_dispatch(core)

    # Product dispatch exists from this point forward. Shared exports/previews/lifecycle layers
    # can therefore operate through one MEP/CIP boundary without reimplementing calculations.
    register_schedule_exports(app, core)
    install_calculation_explanations(core)
    install_mep_sow_erp_wording(core)
    register_precision_routes(app, core)
    register_detail_preview(app, core)
    register_precision_startup(app)
    register_revision_history(app, core)
    register_revision_rationale_controls(app, core)
    register_assumption_routes(app, core)
    register_estimate_delete(app, core)


def _register_sow_capabilities(app, core) -> None:
    # Document composition wrappers are installed before SOW routes so both review PDF and Word
    # generation see the same controlled source/template behavior.
    install_sow_signature_layout()
    install_sow_review_pdf_watermark()
    register_sow_template_reconciliation(app)

    # Net New product dispatch: MEP foundation first, then CIP product specialization.
    register_sow(app, core)
    register_cip_sow(app, core)

    # Four-family template administration and Small Project dispatch layer over the accepted
    # Net New workflow. Shared approval/rejection routes remain owned by sow_routes.
    register_small_project_template_admin(app, core)
    register_small_project_sow_templates(app)
    register_small_project_sow_workflow(app, core)

    # Creation lineage is the final create wrapper; Tools Admin owns the remaining template
    # download boundary; controlled Word is intentionally registered last for all four families.
    register_sow_lineage_carry_forward(app, core)
    register_tools_admin_runtime(app, core)
    install_small_project_word_dispatch()
    register_controlled_sow_word(app, core)


def configure_application(app, core) -> None:
    """Build the production application in one explicit, regression-protected order."""

    # Warning/persistence hardening is installed before any route is registered or startup
    # callback can execute. It changes compatibility plumbing only, not calculation/document
    # behavior or persisted timestamp semantics.
    install_warning_hardening(core)

    _configure_roles()
    app.title = "Cloud Inventory Services Estimator"
    app.version = RELEASE_VERSION
    configure_templates(core.templates)

    _register_estimate_capabilities(app, core)
    _register_sow_capabilities(app, core)

    # This converts the previous implicit registration order into an executable contract. A
    # missing, duplicate or unexpectedly-owned shared route prevents a release from silently
    # changing product/family dispatch behavior.
    assert_final_route_owners(app)

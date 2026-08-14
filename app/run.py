from __future__ import annotations

from . import main as core
from .enhancements import configure_templates, register_routes, clean_schedule_tasks
from .estimate_numbering import register_numbered_estimate_route

app = core.app

configure_templates(core.templates)
register_routes(app)
register_numbered_estimate_route(app, core)

# Main routes resolve generate_schedule from app.main globals at runtime, so replacing
# that global lets us normalize user-facing schedule terminology without changing the
# approved schedule rule source or cell-derived task mapping.
_original_generate_schedule = core.generate_schedule


def _generate_schedule_with_normalized_text(db, rev, replace=True):
    tasks = _original_generate_schedule(db, rev, replace=replace)
    return clean_schedule_tasks(tasks)


core.generate_schedule = _generate_schedule_with_normalized_text

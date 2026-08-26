from __future__ import annotations

from . import main as core
from .application_bootstrap import configure_application


app = core.app
configure_application(app, core)

__all__ = ["app"]

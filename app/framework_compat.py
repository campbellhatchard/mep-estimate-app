from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from starlette.templating import Jinja2Templates


_INSTALLED = False
_ORIGINAL_TEMPLATE_RESPONSE = Jinja2Templates.TemplateResponse


def _compat_on_event(self: FastAPI, event_type: str):
    """Preserve legacy startup/shutdown registration without FastAPI's deprecated decorator.

    The application still has several registration modules that expose startup callbacks.
    Routing them directly to Starlette's existing startup/shutdown handler lists keeps the
    execution contract unchanged while removing the deprecated `FastAPI.on_event()` call.
    A future architectural release can convert the callbacks themselves to one lifespan
    context without mixing that larger change into this warning-hardening release.
    """
    if event_type == "startup":
        handlers = self.router.on_startup
    elif event_type == "shutdown":
        handlers = self.router.on_shutdown
    else:
        raise ValueError(f"Unsupported application event type: {event_type}")

    def decorator(func):
        handlers.append(func)
        return func

    return decorator


def _compat_template_response(self: Jinja2Templates, *args: Any, **kwargs: Any):
    """Translate the application's legacy TemplateResponse call shape to Starlette 0.50+.

    Existing routes pass `(name, context, ...)`. Starlette now expects `(request, name,
    context, ...)`. This adapter changes only the invocation shape; template name, context,
    status, headers, media type and background task are forwarded unchanged.
    """
    if args and isinstance(args[0], str):
        name = args[0]
        context = args[1] if len(args) > 1 else kwargs.pop("context", None)
        status_code = args[2] if len(args) > 2 else kwargs.pop("status_code", 200)
        headers = args[3] if len(args) > 3 else kwargs.pop("headers", None)
        media_type = args[4] if len(args) > 4 else kwargs.pop("media_type", None)
        background = args[5] if len(args) > 5 else kwargs.pop("background", None)
        if len(args) > 6:
            raise TypeError("Too many positional arguments for TemplateResponse")
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected TemplateResponse argument(s): {unexpected}")
        context = context or {}
        request = context.get("request")
        if request is None:
            raise ValueError("TemplateResponse context must include the request object")
        return _ORIGINAL_TEMPLATE_RESPONSE(
            self,
            request,
            name,
            context,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )
    return _ORIGINAL_TEMPLATE_RESPONSE(self, *args, **kwargs)


def install_framework_compatibility() -> None:
    """Install narrow compatibility adapters before any application module is imported."""
    global _INSTALLED
    if _INSTALLED:
        return
    FastAPI.on_event = _compat_on_event  # type: ignore[assignment]
    Jinja2Templates.TemplateResponse = _compat_template_response  # type: ignore[assignment]
    _INSTALLED = True

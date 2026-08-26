from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RouteOwner:
    """Final ownership contract for a shared application route."""

    path: str
    method: str
    module: str
    capability: str


def matching_routes(app, path: str, method: str):
    method = method.upper()
    return [
        route
        for route in app.router.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", set()) or set())
    ]


def take_route(app, path: str, method: str):
    """Remove one existing route and return its endpoint for controlled delegation.

    Runtime layering in the legacy estimator relies on capturing the prior endpoint and
    delegating back to it for the product/family that is not being intercepted.  Keep that
    behavior, but fail immediately if registration order has produced an ambiguous duplicate.
    """

    matches = matching_routes(app, path, method)
    if len(matches) > 1:
        owners = ", ".join(
            f"{getattr(route.endpoint, '__module__', '?')}.{getattr(route.endpoint, '__name__', '?')}"
            for route in matches
        )
        raise RuntimeError(
            f"Route interception is ambiguous for {method.upper()} {path}: {owners}"
        )
    if not matches:
        return None
    route = matches[0]
    app.router.routes.remove(route)
    return route.endpoint


def remove_route(app, path: str, method: str) -> None:
    """Remove an existing route when the prior endpoint is intentionally discarded."""

    take_route(app, path, method)


FINAL_ROUTE_OWNERS: tuple[RouteOwner, ...] = (
    RouteOwner("/estimates", "GET", "app.cip_routes_repository", "Estimate repository"),
    RouteOwner("/estimates/new", "GET", "app.cip_routes_repository", "Product selection"),
    RouteOwner("/estimates/new", "POST", "app.cip_routes_repository", "MEP/CIP estimate creation"),
    RouteOwner("/estimate/{rid}", "GET", "app.cip_routes_estimate", "MEP/CIP estimate authoring"),
    RouteOwner("/estimate/{rid}", "POST", "app.cip_routes_estimate", "MEP/CIP estimate save"),
    RouteOwner("/estimate/{rid}/new-revision", "POST", "app.estimate_revision_controls", "Revision rationale and creation"),
    RouteOwner("/estimate/{rid}/revisions", "GET", "app.estimate_revision_controls", "Revision history"),
    RouteOwner("/estimate/{rid}/status/{action}", "POST", "app.revision_history", "Estimate approval lifecycle"),
    RouteOwner("/estimate/{rid}/jira.csv", "GET", "app.schedule_exports_runtime", "Persisted Schedule Jira export"),
    RouteOwner("/estimate/{rid}/schedule.csv", "GET", "app.schedule_exports_runtime", "Persisted Schedule CSV export"),
    RouteOwner("/estimate/{rid}/sow", "GET", "app.sp_routes_b", "Four-family SOW entry dispatch"),
    RouteOwner("/estimate/{rid}/sow/create", "POST", "app.sow_lineage_runtime", "Four-family SOW create plus lineage"),
    RouteOwner("/sow/{sid}", "GET", "app.sp_routes_b", "Four-family SOW page dispatch"),
    RouteOwner("/sow/{sid}/save", "POST", "app.sp_routes_b", "Four-family SOW save dispatch"),
    RouteOwner("/sow/{sid}/finalize", "POST", "app.sp_routes_b", "Four-family SOW finalize dispatch"),
    RouteOwner("/sow/{sid}/send-approval", "POST", "app.sow_routes", "Shared SOW approval submission"),
    RouteOwner("/sow/{sid}/approve", "POST", "app.sp_routes_b", "Four-family SOW approval dispatch"),
    RouteOwner("/sow/{sid}/reject", "POST", "app.sow_routes", "Shared SOW rejection"),
    RouteOwner("/sow/{sid}/new-revision", "POST", "app.sp_routes_b", "Four-family rejected SOW revision"),
    RouteOwner("/sow/{sid}/pdf", "GET", "app.sp_routes_b", "Four-family SOW review PDF"),
    RouteOwner("/sow/{sid}/docx", "GET", "app.sow_word_control", "Controlled Word boundary"),
    RouteOwner("/admin/sow-templates", "GET", "app.small_project_template_admin", "Four-family SOW template administration"),
    RouteOwner("/admin/sow-templates/upload", "POST", "app.small_project_template_admin", "Four-family SOW template upload"),
    RouteOwner("/admin/sow-templates/{tid}/activate", "POST", "app.small_project_template_admin", "Four-family SOW template activation"),
    RouteOwner("/admin/sow-templates/{tid}/download", "GET", "app.tools_admin_runtime", "Controlled SOW template download"),
)


def assert_final_route_owners(app, owners: Iterable[RouteOwner] = FINAL_ROUTE_OWNERS) -> None:
    """Fail startup/test registration when a shared route is missing, duplicated or mis-owned."""

    errors: list[str] = []
    for owner in owners:
        matches = matching_routes(app, owner.path, owner.method)
        if len(matches) != 1:
            errors.append(
                f"{owner.method} {owner.path} expected one final owner for {owner.capability}; found {len(matches)}"
            )
            continue
        endpoint = matches[0].endpoint
        actual_module = getattr(endpoint, "__module__", "")
        if actual_module != owner.module:
            errors.append(
                f"{owner.method} {owner.path} expected {owner.module} for {owner.capability}; found {actual_module}"
            )
    if errors:
        raise RuntimeError("Final route ownership contract failed: " + " | ".join(errors))

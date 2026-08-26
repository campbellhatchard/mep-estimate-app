from app.run import app


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_v0318_merge_ref_integration_gate():
    """Protect the v0.3.18 route baseline without blocking later releases."""
    assert _version_tuple(app.version) >= (0, 3, 18, 0)
    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/data", "GET") in paths
    assert ("/admin/sow-templates", "GET") in paths
    assert ("/estimate/{rid}/calculations", "GET") in paths

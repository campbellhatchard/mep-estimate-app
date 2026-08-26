from app.run import app


def test_v0318_merge_ref_integration_gate():
    """Force stacked release CI to validate v0.3.18 against its current base."""
    assert app.version == "0.3.18.0"
    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/data", "GET") in paths
    assert ("/admin/sow-templates", "GET") in paths
    assert ("/estimate/{rid}/calculations", "GET") in paths

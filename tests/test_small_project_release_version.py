from app.run import app


def test_small_project_workflow_release_version():
    assert app.version == "0.3.16.0"

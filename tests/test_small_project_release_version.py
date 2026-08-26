from app.run import app


def test_estimator_release_version():
    assert app.version == "0.3.21.0"

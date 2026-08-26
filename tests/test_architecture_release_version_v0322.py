from app.application_bootstrap import RELEASE_VERSION
from app.run import app


def test_v0322_bootstrap_release_version_is_active():
    assert RELEASE_VERSION == "0.3.22.0"
    assert app.version == RELEASE_VERSION

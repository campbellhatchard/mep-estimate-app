from pathlib import Path

from app.application_bootstrap import RELEASE_VERSION
from app.jira_relationships import JIRA_RELATIONSHIP_COLUMNS, RELATIONSHIP_CAPACITY
from app.run import app


def test_v0325_release_wiring_and_controlled_jira_capacity():
    assert RELEASE_VERSION == "0.3.25.0"
    assert app.version == RELEASE_VERSION
    assert RELATIONSHIP_CAPACITY == {
        "BLOCKS": 6,
        "DISCOVERY_CONNECTED": 1,
        "RELATES": 2,
    }
    assert JIRA_RELATIONSHIP_COLUMNS["BLOCKS"] == (
        (7, 8), (9, 10), (11, 12), (13, 14), (15, 16), (17, 18)
    )
    bootstrap = Path("app/application_bootstrap.py").read_text(encoding="utf-8")
    schedule = Path("app/templates/schedule.html").read_text(encoding="utf-8")
    jira_models = Path("app/jira_models.py").read_text(encoding="utf-8")
    migration = Path("migrations/versions/f84a1d6c27b3_jira_schedule_relationships.py").read_text(
        encoding="utf-8"
    )
    assert "register_jira_relationship_routes(app, core)" in bootstrap
    assert "/estimate/{{ rev.id }}/jira-relationships" in schedule
    # v0.3.23 established deprecated UTC defaults as a release-blocking warning class.
    assert "datetime.utcnow" not in jira_models
    assert "default=utc_now" in jira_models
    assert 'revision = "f84a1d6c27b3"' in migration
    assert 'down_revision = "b72e19c4d3a8"' in migration

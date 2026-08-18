import os
from pathlib import Path

import pytest


# Establish a deterministic test environment before any application module is imported.
# Individual tests may still override these values, but isolated test execution must not
# depend on another test module having run first.
TEST_DB = Path('/tmp/mep_estimate_pytest.db')
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB}'
os.environ['SESSION_SECRET'] = 'pytest-secret'
os.environ['ADMIN_PASSWORD'] = 'TestPass123!'


def pytest_collection_modifyitems(config, items):
    """The original v0.3.2 monolithic SOW lifecycle test was useful during initial build,
    but it obscured which approval control failed. Focused end-to-end tests now cover
    queue assignment, rejection/revision, approval locking and assumption generation.
    Keep the original scenario in source as design documentation, but do not execute it.
    """
    for item in items:
        if item.nodeid.endswith(
            "test_zzz_sow.py::test_sow_workflow_role_queue_rejection_revision_and_approval_lock"
        ):
            item.add_marker(pytest.mark.skip(reason="Superseded by focused SOW lifecycle regression controls"))

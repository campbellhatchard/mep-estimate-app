import os
import sys
from pathlib import Path

import pytest


def _is_e2e_run() -> bool:
    return os.getenv("E2E_RUN") == "1" or any(
        "tests/e2e" in str(arg).replace("\\", "/") for arg in sys.argv[1:]
    )


# Establish a deterministic SQLite test environment before any application module is
# imported. Explicit E2E runs preserve the caller's PostgreSQL DATABASE_URL instead.
if not _is_e2e_run():
    TEST_DB = Path('/tmp/mep_estimate_pytest.db')
    if TEST_DB.exists():
        TEST_DB.unlink()
    os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB}'
    os.environ['SESSION_SECRET'] = 'pytest-secret'
    os.environ['ADMIN_PASSWORD'] = 'TestPass123!'
    os.environ['SOW_TRACK_CHANGES_PASSWORD'] = 'Pytest-SOW-Track-Changes-123!'


def pytest_collection_modifyitems(config, items):
    """Retain the historical monolithic SOW case as source documentation only."""
    for item in items:
        if item.nodeid.endswith(
            "test_zzz_sow.py::test_sow_workflow_role_queue_rejection_revision_and_approval_lock"
        ):
            item.add_marker(pytest.mark.skip(reason="Superseded by focused SOW lifecycle regression controls"))

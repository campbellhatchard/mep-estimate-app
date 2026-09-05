import os
from pathlib import Path

import pytest


def _e2e_explicitly_requested(config) -> bool:
    if os.getenv("E2E_RUN") == "1":
        return True
    args = [str(arg).replace("\\", "/") for arg in config.invocation_params.args]
    return any("tests/e2e" in arg for arg in args)


def pytest_ignore_collect(collection_path: Path, config):
    normalized = str(collection_path).replace("\\", "/")
    if "tests/e2e" in normalized and not _e2e_explicitly_requested(config):
        return True
    return False


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.nodeid.endswith(
            "test_zzzb_sow_approval.py::test_sow_approval_locks_content_hash_and_regenerates_word"
        ):
            item.add_marker(pytest.mark.skip(reason="Superseded by isolated SOW approval lock regression"))

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.nodeid.endswith(
            "test_zzzb_sow_approval.py::test_sow_approval_locks_content_hash_and_regenerates_word"
        ):
            item.add_marker(pytest.mark.skip(reason="Superseded by isolated SOW approval lock regression"))

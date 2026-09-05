from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

from tests.e2e.support.users import USERS, ensure_e2e_users


@pytest.fixture(scope="session")
def app_url() -> str:
    value = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    host = (urlparse(value).hostname or "").lower()
    if host not in {"127.0.0.1", "localhost"}:
        pytest.fail(f"Unsafe E2E target {value!r}; Phase 1 browser tests may run only on localhost.")
    return value


@pytest.fixture(scope="session", autouse=True)
def synthetic_users(app_url):
    del app_url
    ensure_e2e_users()
    return USERS


@pytest.fixture
def user_specs():
    return USERS


@pytest.fixture
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "ignore_https_errors": False,
    }

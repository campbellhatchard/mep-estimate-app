from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_e2e_dependencies_are_python_only_and_outside_production_runtime():
    e2e = _read("requirements-e2e.txt")
    assert "-r requirements-dev.txt" in e2e
    assert "pytest-playwright==0.9.0" in e2e
    assert "playwright==1.62.0" in e2e

    production = _read("requirements.txt").lower()
    render = _read("render.yaml").lower()
    assert "playwright" not in production
    assert "playwright" not in render
    assert "e2e_" not in render

    for forbidden in ("package.json", "package-lock.json", "playwright.config.ts", "playwright.config.js"):
        assert not (ROOT / forbidden).exists(), forbidden


def test_pytest_keeps_browser_tests_separate_and_has_zero_retry_markers():
    pytest_ini = _read("pytest.ini")
    for marker in ("e2e", "smoke", "release"):
        assert f"{marker}:" in pytest_ini

    root_conftest = _read("conftest.py")
    assert "tests/e2e" in root_conftest.replace("\\", "/")
    assert "E2E_RUN" in root_conftest
    assert "rerun" not in pytest_ini.lower()
    assert "pytest-rerunfailures" not in _read("requirements-e2e.txt").lower()


def test_browser_workflow_uses_ephemeral_postgres_chromium_and_local_fastapi_only():
    workflow = _read(".github/workflows/browser-tests.yml")
    lower = workflow.lower()
    assert "postgres:18" in lower
    assert "alembic upgrade head" in lower
    assert "playwright install --with-deps chromium" in lower
    assert "uvicorn app.run:app" in lower
    assert "/health" in lower
    assert "--browser chromium" in lower
    assert "--tracing retain-on-failure" in lower
    assert "--screenshot only-on-failure" in lower
    assert "upload-artifact" in lower
    assert "firefox" not in lower
    assert "webkit" not in lower
    assert "npm " not in lower
    assert "setup-node" not in lower
    assert "onrender.com" not in lower


def test_e2e_suite_has_phase_one_size_and_localhost_production_safety_guard():
    e2e_dir = ROOT / "tests" / "e2e"
    assert e2e_dir.is_dir()
    test_functions = 0
    for path in e2e_dir.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        test_functions += sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
            for node in tree.body
        )
    assert 12 <= test_functions <= 18, test_functions

    e2e_conftest = _read("tests/e2e/conftest.py")
    assert "127.0.0.1" in e2e_conftest
    assert "localhost" in e2e_conftest
    assert "Unsafe E2E target" in e2e_conftest


def test_automated_testing_architecture_and_coverage_matrix_are_version_controlled():
    architecture = _read("docs/AUTOMATED_TESTING_ARCHITECTURE.md")
    coverage = _read("docs/AUTOMATED_TEST_COVERAGE.md")
    assert "PostgreSQL 18" in architecture
    assert "Chromium" in architecture
    assert "Golden" in architecture
    assert "Production" in architecture
    assert "Section 15" in coverage
    assert "Audit" in coverage
    assert "Gap" in coverage or "gap" in coverage

"""🧪 RunTestsTool —  pytest """

from __future__ import annotations

from pathlib import Path

import pytest

from jimmy.tools.builtin.run_tests import RunTestsArgs, RunTestsTool


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:

    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n")
    return tmp_path


def test_run_tests_passing_suite(workspace: Path) -> None:
    tests = workspace / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n")

    result = RunTestsTool().execute(RunTestsArgs(path="tests"))

    assert result.success
    assert "passed" in result.output
    assert "Failing" not in result.output


def test_run_tests_failing_suite_reports_names(workspace: Path) -> None:
    tests = workspace / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    (tests / "test_bad.py").write_text("def test_bad():\n    assert False\n")

    result = RunTestsTool().execute(RunTestsArgs(path="tests"))

    assert not result.success
    assert "FAILED" in result.output
    assert "test_bad" in result.output
    assert len(result.output.splitlines()) < 30


def test_run_tests_timeout_guard(workspace: Path) -> None:
    tests = workspace / "tests"
    tests.mkdir()
    (tests / "test_slow.py").write_text("import time\ndef test_slow():\n    time.sleep(10)\n")

    result = RunTestsTool().execute(RunTestsArgs(path="tests", timeout=5))

    assert not result.success
    assert result.error is not None
    assert "timed out" in result.error


def test_run_tests_missing_path(workspace: Path) -> None:
    result = RunTestsTool().execute(RunTestsArgs(path="tests"))
    assert not result.success  # pytest

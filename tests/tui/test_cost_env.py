"""CostTracker pricing fallback, Usage availability, env-file loading."""

from __future__ import annotations

import litellm
import pytest

from jimmy.llm.catalog import load_env_file
from jimmy.llm.cost_tracker import CostTracker
from jimmy.llm.types import Usage


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JIMMY_TEST_KEY", raising=False)


def _tracker() -> CostTracker:
    return CostTracker()


def test_cost_via_completion_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "completion_cost", lambda **kw: 0.5, raising=False)
    tracker = _tracker()
    tracker.add(Usage(input_tokens=10, output_tokens=5), "openai/gpt-4o")
    assert tracker.cost_usd == pytest.approx(0.5)


def test_cost_fallback_uses_bare_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """completion_cost raises (unknown 'zai/...') → model_cost lookup on
    the BARE id must still price the call (the $0-in-navbar fix)."""

    def _raise(**kw: object) -> float:
        raise Exception("unknown model")

    monkeypatch.setattr(litellm, "completion_cost", _raise, raising=False)
    monkeypatch.setattr(
        litellm,
        "model_cost",
        {
            "glm-5.3-flash": {
                "input_cost_per_token": 1e-6,
                "output_cost_per_token": 2e-6,
            }
        },
        raising=False,
    )

    tracker = _tracker()
    tracker.add(Usage(input_tokens=100, output_tokens=50), "zai/glm-5.3-flash")
    expected = 100 * 1e-6 + 50 * 2e-6
    assert tracker.cost_usd == pytest.approx(expected)


def test_cost_zero_for_unpriced_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(**kw: object) -> float:
        raise Exception("unknown model")

    monkeypatch.setattr(litellm, "completion_cost", _raise, raising=False)
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    tracker = _tracker()
    tracker.add(Usage(input_tokens=100, output_tokens=50), "weird/model")
    assert tracker.cost_usd == 0.0  # tokens still tracked
    assert tracker.total_tokens == 150


def test_usage_available_without_total_tokens() -> None:
    """The silent-drop fix: providers that omit total_tokens must still
    count as available."""
    usage = Usage(input_tokens=5, output_tokens=2, total_tokens=0)
    assert usage.available is True
    assert Usage().available is False


def test_load_env_file_injects_without_overriding(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "JIMMY_TEST_KEY=from-file\n# comment\nJIMMY_TEST_QUOTED='quoted value'\nMALFORMED_LINE\n"
    )
    monkeypatch.setenv("JIMMY_TEST_KEY", "from-real-env")  # real env wins

    loaded = load_env_file(env_file)

    import os

    assert loaded == 1  # only the quoted one was injected
    assert os.environ["JIMMY_TEST_KEY"] == "from-real-env"
    assert os.environ["JIMMY_TEST_QUOTED"] == "quoted value"


def test_load_env_file_missing_file(tmp_path) -> None:
    assert load_env_file(tmp_path / "nope.env") == 0

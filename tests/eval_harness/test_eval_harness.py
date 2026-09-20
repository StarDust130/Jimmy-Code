"""🧪 Meta-tests — verify the EVAL MACHINERY works correctly.

Not agent tests: these check harness contracts, scoring math, registry
integrity, and smoke-run the OFFLINE suites end-to-end, so a broken
eval can never silently report garbage.  The scorecard prints after
the run (see conftest.py).
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from eval import scoring
from eval.harness import (
    FakeTool,
    ScriptedProvider,
    Trajectory,
    make_usage,
    result,
)
from eval.report import compare_baseline, render_summary, write_results
from eval.run import run_case
from eval.scenarios import SUITES
from eval.scoring import Check, reset_records, score

# ── harness primitives ──────────────────────────────────────────────────


def test_score_math_weighted() -> None:
    checks = [Check("a", True, weight=1.0), Check("b", False, weight=3.0)]
    assert score(checks) == 25.0
    assert score([]) == 0.0
    assert score([Check("x", True), Check("y", True)]) == 100.0


def test_duplicate_detection_counts_repeat_calls() -> None:
    traj = Trajectory()

    async def gen():
        for cid, args in [
            ("c1", {"command": "ls"}),
            ("c2", {"command": "ls"}),
            ("c3", {"command": "ls"}),
            ("c4", {"command": "cat"}),
        ]:
            yield type(
                "E",
                (),
                {"type": "tool_start", "data": {"id": cid, "name": "shell", "arguments": args}},
            )()

    asyncio.run(traj.consume(gen()))
    dups, ratio = traj.duplicates()
    assert dups == 2
    assert abs(ratio - 0.5) < 1e-9


def test_scripted_provider_one_result_per_call_and_callable_script() -> None:
    provider = ScriptedProvider([result("first"), lambda step, hlen: result(f"dynamic-{step}")])

    async def one_call() -> str:
        out = ""
        async for ev in provider.stream([{"m": 1}]):  # ← no return inside the loop
            if ev.kind == "done":
                out = ev.result.content
        return out

    # 🎯 ONE result per stream() call — stateful across calls
    assert asyncio.run(one_call()) == "first"
    assert asyncio.run(one_call()) == "dynamic-2"


def test_usage_factory() -> None:
    u = make_usage(50, 5)
    assert u.total_tokens == 55 and u.available


def test_fake_tool_records_plain_dicts_and_fails_on_script() -> None:
    tool = FakeTool("write_file", output="written", fail_first=1)

    class _Args:
        def model_dump(self):
            return {"path": "a.py"}

    with pytest.raises(ValueError):
        tool.execute(_Args())
    out = tool.execute(_Args())
    assert out.output == "written"
    assert tool.calls == [{"path": "a.py"}, {"path": "a.py"}]


# ── registry integrity ──────────────────────────────────────────────────


def test_every_scenario_is_valid() -> None:
    for suite, cases in SUITES.items():
        assert cases, f"suite {suite} is empty"
        for case_id, fn in cases:
            assert isinstance(case_id, str) and case_id
            assert inspect.iscoroutinefunction(fn), f"{suite}/{case_id} not async"
    ids = [cid for cases in SUITES.values() for cid, _ in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids across suites"


# ── smoke: offline suites run end-to-end, all green, scorecard works ────


def test_offline_suites_all_green() -> None:
    reset_records()
    for suite, cases in SUITES.items():
        for case_id, fn in cases:
            run_case(suite, case_id, fn)

    rows = scoring.RECORDS
    assert len(rows) == sum(len(c) for c in SUITES.values())
    crashed = [r for r in rows if r.error]
    assert not crashed, [f"{r.suite}/{r.case}: {r.error}" for r in crashed]

    failures = [r for r in rows if not r.passed]
    assert not failures, [
        f"{r.suite}/{r.case}: failed={r.failed} "
        f"details={ {k: r.details.get(k, '') for k in r.failed} }"
        for r in failures
    ]

    # 🔬 the headline metric is measured and documents the known bug
    endurance = next(r for r in rows if r.case == "dumb_loop_endurance")
    assert endurance.metrics["duplicate_ratio"] > 0.5

    lines = render_summary()
    assert "JIMMY EVAL SCORECARD" in lines[1]
    path = write_results("offline")
    assert path.exists() and '"overall"' in path.read_text()


def test_baseline_regression_diff(tmp_path, monkeypatch) -> None:
    import eval.report as report

    monkeypatch.setattr(report, "RESULTS_DIR", tmp_path)
    reset_records()
    run_case("small", "tool_choice_read", SUITES["small"][0][1])
    rows = list(scoring.RECORDS)

    path = write_results("offline")
    (tmp_path / "baseline.json").write_text(path.read_text())
    assert compare_baseline(rows) == []  # same scores → no regression

    for r in rows:
        r.score = 0.0
    warns = compare_baseline(rows)
    assert warns and "REGRESSION" in warns[0]

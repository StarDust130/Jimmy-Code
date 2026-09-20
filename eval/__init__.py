"""🧪 Jimmy eval — production agent evaluation (repo-root package).

    python -m eval.run                    # 🧪 offline suites (hermetic, free)
    python -m eval.run --suite big        # one suite
    python -m eval.run --save-baseline    # 📌 pin scores
    python -m eval.run --live             # 🌐 real model + real tools
    python -m eval.run --fail-under 85    # CI gate

Only the provider/tools are fakes; the loop, context builder,
permissions, sessions and TUI are the real code under test.

NOTE: deliberately NO imports of `eval.run` here — `python -m eval.run`
executes run.py as __main__, and importing it from the package __init__
causes a sys.modules RuntimeWarning.
"""

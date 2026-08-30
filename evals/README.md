# Jimmy Eval Harness

Run this from the **Jimmy repo root** (`D:\Projects\Jimmy`).

The harness uses the real Jimmy code and its `.venv`, but every eval task gets a fresh temporary Git workspace. Your real repo is never used as the agent workspace.

## Run

From PowerShell:

```powershell
cd D:\Projects\Jimmy
uv run python evals\runner.py
```

One task:

```powershell
uv run python evals\runner.py --task E07
```

Keep a failed workspace for debugging:

```powershell
uv run python evals\runner.py --task E07 --keep-workspaces
```

## What it measures

- pass/fail
- LLM turns
- tool calls
- failed tools
- repeated tool calls
- forbidden/wrong tool use
- changed files
- latency
- Gemini rate-limit waits/retries

## Important

Run sequentially for now. Your Gemini limit is about 15 requests/minute; parallel evals would only make that worse and would make latency measurements noisy.

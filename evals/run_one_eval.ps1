# Run from the Jimmy repo root.
# Example: .\evals\run_one_eval.ps1 E07
param([Parameter(Mandatory=$true)][string]$TaskId)
uv run python evals\runner.py --task $TaskId --keep-workspaces

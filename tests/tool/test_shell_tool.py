from pathlib import Path

from jimmy.tools.builtin.shell import ShellArgs, ShellTool


def test_successful_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Run a simple command
    result = ShellTool().execute(ShellArgs(command="printf 'hello'"))

    # 3️⃣ Check the successful result
    assert result.success is True
    assert result.output == "hello"
    assert result.error is None


def test_stdout_and_stderr(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Write to stdout and stderr
    result = ShellTool().execute(ShellArgs(command="printf 'out'; printf 'err' >&2"))

    # 3️⃣ Check both outputs
    assert result.success is True
    assert "out" in result.output
    assert "stderr" in result.output
    assert "err" in result.output


def test_non_zero_exit_code(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Run a command that fails
    result = ShellTool().execute(ShellArgs(command="exit 1"))

    # 3️⃣ Check the failure result
    assert result.success is False

    # 4️⃣ Make sure an error exists
    assert result.error is not None
    assert "Exit code: 1" in result.error


def test_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Run a command longer than the timeout
    result = ShellTool().execute(
        ShellArgs(
            command="sleep 2",
            timeout=1,
        )
    )

    # 3️⃣ Check that it timed out
    assert result.success is False

    # 4️⃣ Make sure an error exists
    assert result.error is not None
    assert "timed out" in result.error


def test_runs_inside_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Run pwd inside the workspace
    result = ShellTool().execute(ShellArgs(command="pwd"))

    # 3️⃣ Check the command used the workspace
    assert result.success is True
    assert str(tmp_path) in result.output

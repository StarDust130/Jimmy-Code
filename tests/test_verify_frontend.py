from pathlib import Path

from jimmy.tools.filesystem import Filesystem
from jimmy.tools.verify_frontend import VerifyFrontendInput, VerifyFrontendTool


def test_verifies_linked_static_assets(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text('<link rel="stylesheet" href="style.css"><script src="script.js"></script>')
    (app / "style.css").write_text("body {}")
    (app / "script.js").write_text("const ready = true;")

    result = VerifyFrontendTool(Filesystem(tmp_path)).execute(VerifyFrontendInput(directory="app"))

    assert result.success is True
    assert "script.js" in result.output


def test_reports_missing_linked_asset(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text('<script src="missing.js"></script>')

    result = VerifyFrontendTool(Filesystem(tmp_path)).execute(VerifyFrontendInput(directory="app"))

    assert result.success is False
    assert "missing.js" in result.error

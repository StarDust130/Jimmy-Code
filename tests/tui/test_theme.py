"""Theme engine tests — pure + one app-level set_theme test."""

from __future__ import annotations

from conftest import leave_home, tui_test

from tui.kit.theme import CYBER, THEME, THEMES, THEME_ORDER, flow, rebuild_flow


def test_theme_defaults() -> None:
    assert THEME["name"] == "violet"
    assert set(THEME_ORDER) == {"violet", "ember", "frost", "matrix"}
    assert set(THEMES) == set(THEME_ORDER)


def test_flow_reads_the_precomputed_palette() -> None:
    assert flow(0.0) == CYBER[0]
    assert flow(1.0) == CYBER[255]
    assert all(color.startswith("#") for color in CYBER)
    assert len(CYBER) == 256


def test_rebuild_flow_replaces_contents_in_place() -> None:
    before = list(CYBER)
    rebuild_flow(THEMES["ember"]["stops"])
    assert CYBER != before
    rebuild_flow(THEMES["violet"]["stops"])
    assert CYBER == before


def test_theme_specs_have_required_keys() -> None:
    for name in THEME_ORDER:
        spec = THEMES[name]
        assert {"stops", "accent", "accent2"} <= set(spec)
        assert spec["accent"].startswith("#")


@tui_test
async def test_app_set_theme_updates_state(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        app.set_theme("matrix")
        assert THEME["name"] == "matrix"
        assert THEME["accent"] == THEMES["matrix"]["accent"]
        assert THEME["accent2"] == THEMES["matrix"]["accent2"]

        app.set_theme("does-not-exist")  # unknown name → no-op
        assert THEME["name"] == "matrix"

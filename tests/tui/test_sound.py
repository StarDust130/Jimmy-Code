"""SoundPlayer semantics — never spawns a real audio subprocess.

The "no player found" path is deliberately NOT tested with a wall-clock
sleep: ``shutil.which`` does real disk I/O on PATH and can legitimately
take longer than any small timeout while ``is_playing`` reports the
"starting" window.  The real guarantee is behavioral: ctrl+s stops,
ctrl+s again restarts from the top (exercised via FakeSound in the app
tests and verified manually).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from tui.kit.sound import SoundPlayer


def test_sound_player_idle_by_default() -> None:
    assert SoundPlayer().is_playing is False


def test_play_without_path_is_a_noop() -> None:
    sp = SoundPlayer()

    async def scenario() -> None:
        sp.play(None)
        await asyncio.sleep(0)
        assert sp.is_playing is False

    asyncio.run(scenario())


def test_stop_is_idempotent() -> None:
    sp = SoundPlayer()
    sp.stop()
    sp.stop()
    assert sp.is_playing is False


def test_locate_song_returns_none_or_existing_path() -> None:
    result = SoundPlayer().locate_song()
    assert result is None or (isinstance(result, Path) and result.is_file())

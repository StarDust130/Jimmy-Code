"""Sound playback — full-track, async, never blocks the UI."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from rich.text import Text


class SoundPlayer:
    """Fire-and-forget playback of ``public/song.mp3`` — the FULL track.

    Playback is delegated to whatever media CLI already exists on PATH
    (afplay / mpv / ffplay / mpg123) and runs on an asyncio subprocess.
    No timeout — the whole song plays end to end.  ``is_playing`` is the
    single source of truth for every UI indicator.
    """

    CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("afplay", ()),  # macOS
        ("mpv", ("--no-video", "--really-quiet")),  # linux/bsd
        ("ffplay", ("-nodisp", "-autoexit", "-loglevel", "quiet")),
        ("mpg123", ("-q",)),
    )

    def __init__(self) -> None:
        self._resolved = False
        self._command: tuple[str, ...] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None  # strong ref, no GC
        self._starting = False  # play() requested

    @property
    def is_playing(self) -> bool:
        """True while a song is sounding (or about to start)."""
        process = self._process
        if process is not None and process.returncode is None:
            return True
        return self._starting

    def locate_song(self) -> Path | None:
        """Find public/song.mp3 relative to the project root or CWD."""
        here = Path(__file__).resolve()
        for base in (here.parents[3], here.parents[2], here.parents[1], Path.cwd()):
            candidate = base / "public" / "song.mp3"
            if candidate.is_file():
                return candidate
        return None

    def play_startup(self) -> None:
        """(Re)start the song from the beginning."""
        self.play(self.locate_song())

    def play(self, path: Path | None) -> None:
        """Schedule playback inside a task — safe to call from anywhere."""
        if path is None:
            self._starting = False
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._starting = False
            return
        self.stop()
        self._starting = True
        self._task = loop.create_task(self._play(path))

    def stop(self) -> None:
        """Kill any in-flight playback (used on quit and on stop)."""
        self._starting = False
        process = self._process
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        self._process = None

    async def _play(self, path: Path) -> None:
        if not self._resolved:
            self._resolved = True
            for name, arguments in self.CANDIDATES:
                found = await asyncio.to_thread(shutil.which, name)
                if found:
                    self._command = (found, *arguments)
                    break
        if self._command is None:
            self._starting = False
            return
        command = self._command
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (OSError, ValueError):
            self._command = None
            self._starting = False
            return
        self._starting = False
        try:
            await self._process.wait()  # WHOLE song — no cutoff
        except asyncio.CancelledError:
            self.stop()
            raise


def sound_chip_text(playing: bool) -> Text:
    """Render the compact sound status chip."""

    if playing:
        return Text.from_markup("[#67E8F9]🔊[/] [#8A91A8]sound[/]")
    
    return Text.from_markup("[#8A91A8]🔇[/] [#8A91A8]muted[/]")

"""Timeline message blocks: user, assistant (streaming), error card,
system notes, pair divider, empty state."""

from __future__ import annotations

import time
from typing import Any, Callable

from rich.markdown import Markdown as RichMarkdown
from rich.markup import escape
from rich.text import Text
from textual import errors, events
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from ..kit.assets import gradient_text
from ..kit.helpers import classify_error, error_detail, jimmy, pretty_pwd
from ..kit.theme import THEME


class PairDivider(Static):
    """A thin hairline after each completed prompt+reply pair."""

    def __init__(self) -> None:
        super().__init__("", classes="pair-divider")


class AssistantMessage(Vertical):
    """Assistant response block — streams plain text with a live cursor,
    then upgrades ONCE to full Rich Markdown (monokai code theme)."""

    STREAM_THROTTLE = 0.03

    def __init__(self) -> None:
        super().__init__(classes="msg msg-assistant")
        self._chunks: list[str] = []
        self._last_render = 0.0
        self._finished = False
        self._frame = 0
        self._body = Static("", classes="assistant-body")

    def compose(self) -> Any:
        yield self._body

    @property
    def raw_text(self) -> str:
        return "".join(self._chunks).strip()

    def _safe_body_update(self, content: Any) -> None:
        try:
            self._body.update(content)
        except errors.NoWidget:
            pass

    def append(self, chunk: str) -> None:
        if not chunk or self._finished:
            return
        self._chunks.append(chunk)
        now = time.monotonic()
        if now - self._last_render >= self.STREAM_THROTTLE:
            self._last_render = now
            self._render_stream()

    def _render_stream(self) -> None:
        self._frame += 1
        cursor = THEME["accent2"] if self._frame % 2 == 0 else THEME["accent"]
        text = escape("".join(self._chunks))
        self._safe_body_update(Text.from_markup(f"{text}[{cursor}]▍[/]"))

    def finish_markdown(self) -> None:
        if self._finished:
            return
        self._finished = True
        raw = self.raw_text
        if not raw:
            self.remove()
            return
        self._safe_body_update(RichMarkdown(raw, code_theme="monokai"))


class UserMessage(Static):
    """`❯ your prompt` — blue marker + gradient prompt text.

    Text() never interprets markup, so pasted prompts are injection-safe.
    """

    def __init__(self, text: str) -> None:
        rendered = Text()
        rendered.append("❯ ", style="bold #60a5fa")
        rendered.append_text(gradient_text(text, "#a5c8ff", "#c4b5fd"))
        super().__init__(rendered, classes="msg msg-user")


class ErrorCard(Vertical):
    """A friendly, classified error card with retry + expandable details
    + optional extra actions (e.g. '🤖 Change model').

    ╭──────────────────────────────────────────╮
    │ ✕  🤖 Model 'x' isn't available          │
    │ It may be retired or need a plan change. │
    │ 🤖 Change model   ↻ retry   ⌄ details    │
    ╰──────────────────────────────────────────╯
    """

    def __init__(self, error: BaseException) -> None:
        icon, title, message = classify_error(error)
        self._icon = icon
        self._title = title
        self._message = message
        self._detail = error_detail(error)
        self._extra_actions: list[tuple[str, Callable[[], None]]] = []
        super().__init__(classes="error-card")

    def attach_action(self, label: str, callback: Callable[[], None]) -> None:
        """➕ Register an extra clickable action row.

        Must be called BEFORE the card is mounted (i.e. before it is
        appended to the chat) — the row is built in compose().
        """
        self._extra_actions.append((label, callback))

    def compose(self) -> Any:
        yield Static(
            Text.from_markup(f"[#fb7185]✕[/]  [bold #fda4af]{self._icon} {escape(self._title)}[/]"),
            classes="err-title",
        )
        yield Static(Text.from_markup(f"[#c7cde4]{escape(self._message)}[/]"), classes="err-msg")
        with Horizontal(classes="err-actions"):
            # ➕ extra actions first (e.g. the fix for THIS error)
            for i, (label, _cb) in enumerate(self._extra_actions):
                yield Static(
                    Text.from_markup(f"[#f5c451]{escape(label)}[/]"),
                    id=f"err-action-{i}",
                    classes="err-action-btn",
                )
            yield Static(Text.from_markup("[#fbbf24]↻[/] [#e2e6f2] retry[/]"), id="err-retry")
            yield Static(Text.from_markup("[#565d73]⌄[/] [#8a91a8] details[/]"), id="err-details")
        yield Static(Text(self._detail), classes="err-detail")

    def on_mount(self) -> None:
        self.tooltip = (
            "extra actions fix THIS error · ↻ retry runs the last prompt · "
            "⌄ details shows the traceback"
        )

    def on_click(self, event: events.Click) -> None:
        event.stop()
        cid = event.control.id

        # ➕ extra actions (registered via attach_action)
        if cid and cid.startswith("err-action-"):
            idx = int(cid.rsplit("-", 1)[-1])
            if 0 <= idx < len(self._extra_actions):
                self._extra_actions[idx][1]()
            return

        if cid == "err-retry":
            if jimmy(self).action_retry_last():
                try:
                    self.remove()
                except Exception:
                    pass
        elif cid == "err-details":
            detail = self.query_one(".err-detail")
            opened = detail.has_class("shown")
            detail.toggle_class("shown")
            label = self.query_one("#err-details", Static)
            if opened:
                label.update(Text.from_markup("[#565d73]⌄[/] [#8a91a8] details[/]"))
            else:
                label.update(Text.from_markup("[#8a91a8]⌃[/] [#8a91a8] details[/]"))


class SystemNote(Static):
    """Dim, italic one-liner for system events (cleared, interrupted…)."""

    def __init__(self, note: str) -> None:
        super().__init__(
            Text.from_markup(f"[#4b5163]· {escape(note)}[/]"),
            classes="msg-system",
        )


class EmptyState(Static):
    """Quiet welcome line before the first message — shows the full pwd."""

    def __init__(self) -> None:
        super().__init__(
            Text.from_markup(
                f"[{THEME['accent']}]✻[/] [#8a91a8]jimmy is ready[/]  "
                f"[#3a4157]·[/]  [#4b5163]{escape(pretty_pwd())}[/]\n"
                f"[#3a4157]describe a task · /help for commands[/]"
            ),
            classes="empty-state",
        )

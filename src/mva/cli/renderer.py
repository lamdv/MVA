"""Streaming event renderer for the MVA REPL.

Renders :class:`Session` event dicts to a :class:`rich.console.Console`,
handling thinking blocks (dim italic), regular content streamed as
**rendered Markdown** via Rich's :class:`rich.live.Live` display, tool
calls, and tool results.

State is tracked between events within a single turn to manage the
transition between thinking, content, and tool-call phases.

Markdown rendering
------------------
When the LLM emits content deltas, the renderer buffers the text and
uses :class:`rich.live.Live` to display the full accumulated content
as rendered Markdown.  This means **bold**, *italic*, ``code``,
```code blocks```, lists, tables, headers, links, and images are all
rendered live as the response streams in.

On each delta, only the Live display area is refreshed — the
"Assistant:" header and any previous thinking text remain static.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

_console = Console()


class EventRenderer:
    """Renders session events to the terminal, tracking per-turn state.

    Uses Rich's :class:`~rich.live.Live` display to render streaming
    Markdown content in-place.  Call :meth:`reset` between turns to
    clear internal phase tracking and stop any active Live display.
    """

    def __init__(self) -> None:
        self.thinking_emitted = False
        self.content_started = False
        self._content_buffer: str = ""
        self._live: Live | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset phase tracking for a new turn and stop any active Live."""
        self._stop_live()
        self.thinking_emitted = False
        self.content_started = False
        self._content_buffer = ""

    def render(self, event: dict[str, Any]) -> None:
        """Render a single session event to the console."""
        event_type = event.get("type")

        if event_type == "thinking":
            self._render_thinking(event)
        elif event_type == "delta":
            self._render_delta(event)
        elif event_type == "tool_call":
            self._render_tool_call(event)
        elif event_type == "tool_result":
            self._render_tool_result(event)
        elif event_type == "done":
            self._render_done()
        elif event_type == "cancelled":
            self._render_cancelled()
        elif event_type == "error":
            self._render_error(event)

    # ------------------------------------------------------------------
    # Live display management
    # ------------------------------------------------------------------

    def _start_live(self) -> None:
        """Start a Rich Live display for streaming Markdown content."""
        if self._live is not None:
            return
        self._live = Live(
            Markdown(""),
            refresh_per_second=12,
            console=_console,
            transient=True,        # keep scrollback clean (avoids frame pollution)
            vertical_overflow="visible",
        )
        self._live.__enter__()

    def _stop_live(self) -> None:
        """Stop the active Live display, leaving final content visible."""
        if self._live is None:
            return
        try:
            self._live.__exit__(None, None, None)
        except Exception:
            pass
        self._live = None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _render_thinking(self, event: dict[str, Any]) -> None:
        """Render a reasoning/thinking text block (dim italic)."""
        if not self.thinking_emitted:
            self.thinking_emitted = True
            _console.print("\n[bold dim]Thinking…[/]", highlight=False)
        _console.print(
            f"[dim italic]{event['content']}[/]",
            end="",
            highlight=False,
        )

    def _render_delta(self, event: dict[str, Any]) -> None:
        """Buffer the content delta and update the Live Markdown display."""
        # Print "Assistant:" header on first content delta
        if not self.content_started:
            self.content_started = True
            if self.thinking_emitted:
                _console.print()  # newline after thinking block
            _console.print("\n[bold cyan]Assistant:[/] ", highlight=False)

        # Buffer and render
        self._content_buffer += event["content"]
        self._start_live()

        # If the buffer is just whitespace, don't render yet
        rendered = Markdown(self._content_buffer) if self._content_buffer.strip() else Markdown("")
        self._live.update(rendered)  # type: ignore[union-attr]

    def _render_tool_call(self, event: dict[str, Any]) -> None:
        """Finalize markdown, then render the tool call below it."""
        self._stop_live()

        name = event["name"]
        args = event.get("args", {})
        args_str = json.dumps(args, indent=2)

        _console.print(
            f"\n  [bold yellow]⚡ {name}[/] [dim]Calling with arguments:[/]",
            highlight=False,
        )
        _console.print(
            f"  [dim italic]{args_str}[/]",
            highlight=False,
        )

        # Reset phase tracking for the next round
        self.thinking_emitted = False
        self.content_started = False
        self._content_buffer = ""

    def _render_tool_result(self, event: dict[str, Any]) -> None:
        """Render a tool execution result (dim green on success, red on error)."""
        preview = event["content"][:120].replace("\n", " ")
        if event["is_error"]:
            _console.print(f"  [red]✗ {preview}[/]", highlight=False)
        else:
            suffix = "…" if len(event["content"]) > 120 else ""
            _console.print(
                f"  [dim green]→ {preview}{suffix}[/]",
                highlight=False,
            )

    def _render_done(self) -> None:
        """Finalize the response — stop the Live display so the terminal
        is in a clean state for the next prompt."""
        self._stop_live()

    def _render_cancelled(self) -> None:
        """Render a cancellation notice."""
        self._stop_live()
        if not self.content_started and not self.thinking_emitted:
            _console.print("\n[dim](empty response)[/]")
        elif self.content_started:
            _console.print()
        _console.print("\n[dim](cancelled)[/]")

    def _render_error(self, event: dict[str, Any]) -> None:
        """Render an error message."""
        self._stop_live()
        _console.print(f"\n[red]Error:[/] {event['content']}")


# ---------------------------------------------------------------------------
# Singleton instance for convenience
# ---------------------------------------------------------------------------

_renderer = EventRenderer()


def render_event(event: dict[str, Any]) -> None:
    """Convenience: render a session event using the singleton renderer."""
    _renderer.render(event)


def reset_renderer() -> None:
    """Convenience: reset the singleton renderer for a new turn."""
    _renderer.reset()

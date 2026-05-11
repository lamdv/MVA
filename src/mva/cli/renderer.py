"""Streaming event renderer for the MVA REPL.

Renders :class:`Session` event dicts to a :class:`rich.console.Console`,
handling thinking blocks (dim italic), streamed content (plain text,
character-by-character), tool calls, and tool results.

State is tracked between events within a single turn to manage the
transition between thinking, content, and tool-call phases.

.. note::

    Content is streamed as **plain text** (not live Markdown) to avoid
    terminal scrollback corruption.  ``rich.live.Live`` uses ANSI escape
    sequences to rewrite its display area; when ``vertical_overflow``
    is set to ``"visible"`` these codes pollute the scrollback buffer,
    causing lines to appear duplicated when the user scrolls up.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console

_console = Console()


class EventRenderer:
    """Renders session events to the terminal, tracking per-turn state.

    Content deltas are streamed directly as plain text (no in-place
    Markdown re-rendering) so the terminal scrollback buffer stays
    clean.  Call :meth:`reset` between turns to clear internal phase
    tracking.
    """

    def __init__(self) -> None:
        self.thinking_emitted = False
        self.content_started = False
        self._content_buffer: str = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset phase tracking for a new turn."""
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
        """Stream the content delta directly to the terminal.

        Plain-text streaming avoids ANSI-escape pollution of the
        scrollback buffer that occurs with ``rich.live.Live`` re-rendering.
        """
        if not self.content_started:
            self.content_started = True
            if self.thinking_emitted:
                _console.print()  # newline after thinking block
            _console.print("\n[bold cyan]Assistant:[/] ", end="", highlight=False)

        self._content_buffer += event["content"]
        _console.print(event["content"], end="", highlight=False)

    def _render_tool_call(self, event: dict[str, Any]) -> None:
        """Render a tool call with its arguments.

        Arguments are parsed from JSON (if received as a string),
        displayed as key: value lines trimmed to 100 chars, wrapped
        in ``---`` horizontal separators.

        Tool calls are streamed as they arrive — the first event
        carries the tool name with (possibly partial) args, and a
        subsequent ``final`` event carries the complete args.  On
        final events the tool name is suppressed to avoid repetition.
        """
        name = event["name"]
        args = event.get("args", {})
        final = event.get("final", False)

        # The API sends arguments as a JSON string; parse it
        if isinstance(args, str) and args.strip():
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                pass  # keep as-is (partial JSON while streaming)

        # Format args as key: value lines, truncated to 100 chars
        if isinstance(args, dict):
            lines = []
            for k, v in args.items():
                v_str = str(v)
                if len(v_str) > 100:
                    v_str = v_str[:100] + "…"
                lines.append(f"{k}: {v_str}")
            args_str = "\n  ".join(lines) if lines else ""
        else:
            args_str = str(args)
            if len(args_str) > 100:
                args_str = args_str[:100] + "…"

        # First emission: show tool name + args between --- separators.
        # Final emission: only show args (name already printed above).
        if not final:
            _console.print(
                f"\n  [bold yellow]⚡ {name}[/]",
                highlight=False,
            )
        if args_str:
            _console.print(
                "  [dim]---[/]",
                highlight=False,
            )
            _console.print(
                f"  [dim italic]{args_str}[/]",
                highlight=False,
            )
            _console.print(
                "  [dim]---[/]",
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
        """Response complete — nothing extra to render (text already streamed)."""
        pass

    def _render_cancelled(self) -> None:
        """Render a cancellation notice."""
        if not self.content_started and not self.thinking_emitted:
            _console.print("\n[dim](empty response)[/]")
        elif self.content_started:
            _console.print()
        _console.print("\n[dim](cancelled)[/]")

    def _render_error(self, event: dict[str, Any]) -> None:
        """Render an error message."""
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

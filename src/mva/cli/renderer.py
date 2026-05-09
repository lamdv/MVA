"""Streaming event renderer for the MVA REPL.

Renders :class:`Session` event dicts to a :class:`rich.console.Console`,
handling thinking blocks (dim italic), regular content (bold cyan),
tool calls (dim), and tool results (dim green/red).

State is tracked between events within a single turn to manage the
transition between thinking, content, and tool-call phases.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

_console = Console()


class EventRenderer:
    """Renders session events to the terminal, tracking per-turn state.

    Call :meth:`reset` between turns to clear internal phase tracking.
    """

    def __init__(self) -> None:
        self.thinking_emitted = False
        self.content_started = False

    def reset(self) -> None:
        """Reset phase tracking for a new turn."""
        self.thinking_emitted = False
        self.content_started = False

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
        elif event_type == "cancelled":
            self._render_cancelled()
        elif event_type == "error":
            self._render_error(event)
        # "done" — nothing to render, content already streamed

    def _render_thinking(self, event: dict[str, Any]) -> None:
        if not self.thinking_emitted:
            self.thinking_emitted = True
            _console.print("\n[bold dim]Thinking…[/]", highlight=False)
        _console.print(
            f"[dim italic]{event['content']}[/]",
            end="",
            highlight=False,
        )

    def _render_delta(self, event: dict[str, Any]) -> None:
        if not self.content_started:
            self.content_started = True
            if self.thinking_emitted:
                _console.print()
            _console.print("\n[bold cyan]Assistant:[/] ", end="", highlight=False)
        _console.print(event["content"], end="", highlight=False)

    def _render_tool_call(self, event: dict[str, Any]) -> None:
        self.thinking_emitted = False
        self.content_started = False
        _console.print(
            f"  [dim]{event['name']}({event['args']})[/]",
            highlight=False,
        )

    def _render_tool_result(self, event: dict[str, Any]) -> None:
        preview = event["content"][:120].replace("\n", " ")
        if event["is_error"]:
            _console.print(f"  [red]✗ {preview}[/]")
        else:
            _console.print(
                f"  [dim green]→ {preview}…[/]"
                if len(event["content"]) > 120
                else f"  [dim green]→ {preview}[/]"
            )

    def _render_cancelled(self) -> None:
        if not self.content_started and not self.thinking_emitted:
            _console.print("\n[dim](empty response)[/]")
        elif self.content_started:
            _console.print()
        _console.print("\n[dim](cancelled)[/]")

    def _render_error(self, event: dict[str, Any]) -> None:
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

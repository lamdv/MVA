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
from rich.syntax import Syntax

_console = Console()

# ---------------------------------------------------------------------------
# Spinner for streaming progress
# ---------------------------------------------------------------------------

from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

_spinner: Progress | None = None


def start_spinner() -> None:
    """Show an animated spinner while waiting for the first token."""
    global _spinner
    if _spinner is not None:
        return  # already running
    _spinner = Progress(
        SpinnerColumn(),
        TextColumn("[dim]{task.description}[/]"),
        TimeElapsedColumn(),
        console=_console,
    )
    _spinner.add_task("Waiting for response…", total=None)


def stop_spinner() -> None:
    """Hide the spinner (content has started flowing)."""
    global _spinner
    if _spinner is not None:
        _spinner.stop()
        _spinner = None


# ---------------------------------------------------------------------------
# Status line helpers — printed as part of normal output (no ANSI conflicts)
# ---------------------------------------------------------------------------

from mva.agent.types import CompletionUsage

_status_session: Any | None = None
"""Session reference for reading provider/model/usage when rendering
the status line before each response."""


def set_status_session(session: Any | None) -> None:
    """Store a session reference for status line rendering."""
    global _status_session
    _status_session = session


def _build_status_text(
    provider: str,
    model: str,
    total_usage: CompletionUsage | None,
) -> str:
    """Build the status line text (used as prefix before streaming)."""
    ctx = f"⚡ {provider or '?'}"
    if model:
        ctx += f" / {model}"
    if total_usage and total_usage.total_tokens > 0:
        pt = _fmt_k(total_usage.prompt_tokens)
        ct = _fmt_k(total_usage.completion_tokens)
        tt = _fmt_k(total_usage.total_tokens)
        ctx += f"  │  📊 {pt}↑ {ct}↓ {tt}∑"
    return ctx


def _fmt_k(n: int) -> str:
    """Format a number, using K suffix for thousands."""
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)


# ---------------------------------------------------------------------------
# Markdown chunk renderer
# ---------------------------------------------------------------------------

from rich.markdown import Markdown


class MarkdownRenderer:
    """Buffers streaming deltas and renders them as Markdown at natural breaks.

    Tracks code fence boundaries so content inside fenced blocks is never
    flushed mid-block (which would produce malformed Markdown output).

    Flushes content at:
    - Code fence closures (`` ``` ``)
    - Blank lines (``\\n\\n``) — inside or outside code blocks
    - Sentence boundaries (``. ``, ``!\\n``, ``?\\n``) — only outside code blocks

    Outside code fences, if the buffer grows beyond *max_buffer_chars* without
    hitting a natural boundary, a word-boundary flush is forced to keep the
    UI responsive.
    """

    def __init__(self, max_buffer_chars: int = 2000) -> None:
        self._buffer = ""
        self._flush_pos = 0
        self._in_code_block = False
        self._max_buffer_chars = max_buffer_chars

    def feed(self, delta: str) -> None:
        """Feed a new text delta and flush any complete chunks."""
        self._buffer += delta
        # Update code-block state from the *full* buffer each time so we
        # correctly track opening/closing fences that span multiple deltas.
        self._sync_code_block_state()
        self._try_flush()

    def flush_all(self) -> None:
        """Flush any remaining buffered content (call on ``done``)."""
        remaining = self._buffer[self._flush_pos :]
        if remaining.strip():
            _console.print(Markdown(remaining, hyperlinks=False))
        self._buffer = ""
        self._flush_pos = 0
        self._in_code_block = False

    def reset(self) -> None:
        """Clear all state for a new turn."""
        self._buffer = ""
        self._flush_pos = 0
        self._in_code_block = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync_code_block_state(self) -> None:
        """Recompute *in_code_block* by counting fences in the full buffer.

        Every pair of `` ``` `` toggles the state.  An odd count means
        we're inside a code block (an opening fence has been seen but
        not yet matched by a closing fence).
        """
        count = self._buffer.count("```")
        self._in_code_block = (count % 2) == 1

    def _try_flush(self) -> None:
        """Flush content up to the last safe break point."""
        unflushed = self._buffer[self._flush_pos :]
        if not unflushed:
            return

        break_at = self._find_break(unflushed)
        if break_at > 0:
            to_render = unflushed[:break_at]
            if to_render.strip():
                _console.print(Markdown(to_render, hyperlinks=False))
            self._flush_pos += break_at
        elif len(unflushed) > self._max_buffer_chars:
            # Force a flush at the last word boundary to keep UI responsive
            word_boundary = unflushed.rfind(" ", 0, self._max_buffer_chars)
            if word_boundary != -1:
                to_render = unflushed[:word_boundary]
                if to_render.strip():
                    _console.print(Markdown(to_render, hyperlinks=False))
                self._flush_pos += word_boundary

    def _find_break(self, text: str) -> int:
        """Find the position of the last safe break point in *text*.

        Break rules:
        - Only break at a **closing** fence: `` ``` `` at a line boundary
          where the full-buffer count *before* it is odd (meaning an
          opening fence has been seen and this is the matching close).
          The rest of the fence line must be empty (no language ID).
          Includes the trailing ``\\n`` so it doesn't linger.
        - Outside a code block: break at blank lines (``\\n\\n``) or
          sentence boundaries (``. ``, ``!\\n``, ``?\\n``).
        - Never break at an **opening** fence (`` ```lang\\n ``) —
          that would flush an empty code block.
        - Never break at blank lines inside a code block — they are
          semantically meaningful whitespace.
        """
        # 1. Closing fence — identified by counting ``` in the full buffer
        #    before this position.  An odd count means this ``` is the
        #    matching close.
        fence_close = text.rfind("```")
        if fence_close != -1:
            end = fence_close + 3
            # Ensure the fence is at a line boundary
            if fence_close == 0 or text[fence_close - 1] == "\n":
                # Count ``` in the FULL buffer before this fence candidate
                count_before = self._buffer[
                    : self._flush_pos + fence_close
                ].count("```")
                # Odd → an opening fence was already seen → this is a CLOSING fence
                if count_before % 2 == 1:
                    # Verify the fence line is bare (no language identifier)
                    rest = text[end:]
                    nl = rest.find("\n")
                    after_fence = rest[:nl] if nl != -1 else rest
                    if after_fence.strip() == "":
                        # Include trailing newline so it doesn't linger
                        return end + (nl + 1 if nl != -1 else len(rest))

        # 2. Blank line — only safe outside code blocks (inside they are
        #    semantically meaningful whitespace in the code)
        if not self._in_code_block:
            blank_line = text.rfind("\n\n")
            if blank_line != -1:
                return blank_line + 2

        # 3. Sentence boundaries — only outside code blocks
        if not self._in_code_block:
            for delim in (". ", "!\n", "?\n"):
                idx = text.rfind(delim)
                if idx != -1:
                    return idx + len(delim)

        # No safe break found
        return 0


# ---------------------------------------------------------------------------
# Event renderer
# ---------------------------------------------------------------------------


class EventRenderer:
    """Renders session events to the terminal, tracking per-turn state.

    By default, content is streamed as **plain text** to avoid scrollback
    issues.  Set ``use_markdown=True`` to render Markdown-formatted output
    chunk-by-chunk instead.
    """

    def __init__(self, use_markdown: bool = False) -> None:
        self.thinking_emitted = False
        self.content_started = False
        self._content_buffer: str = ""
        self._md: MarkdownRenderer | None = (
            MarkdownRenderer() if use_markdown else None
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset phase tracking for a new turn."""
        self.thinking_emitted = False
        self.content_started = False
        self._content_buffer = ""
        if self._md is not None:
            self._md.reset()

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
            self._render_done(event)
        elif event_type == "cancelled":
            self._render_cancelled()
        elif event_type == "error":
            self._render_error(event)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _render_thinking(self, event: dict[str, Any]) -> None:
        """Render a reasoning/thinking text block (dim italic)."""
        stop_spinner()  # content is starting
        if not self.thinking_emitted:
            self.thinking_emitted = True
            _console.print("\n[bold dim]Thinking…[/]", highlight=False)
        _console.print(
            f"[dim italic]{event['content']}[/]",
            end="",
            highlight=False,
        )

    def _render_delta(self, event: dict[str, Any]) -> None:
        """Stream the content delta to the terminal.

        In plain-text mode (default), characters are printed directly.
        In Markdown mode, deltas are buffered and rendered at natural
        sentence/paragraph boundaries.
        """
        stop_spinner()  # content is starting
        if not self.content_started:
            self.content_started = True
            if self.thinking_emitted:
                _console.print()  # newline after thinking block
            _console.print("\n[bold cyan]Assistant:[/] ", end="", highlight=False)

        if self._md is not None:
            # Markdown mode: feed to chunk renderer
            self._md.feed(event["content"])
        else:
            # Plain-text mode: print directly (no scrollback issues)
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
        """Render a tool execution result (dim green on success, red on error).

        If the content contains a ``Diff:`` section (e.g. from the ``edit``
        tool), the diff portion is syntax-highlighted using the ``diff``
        lexer from ``rich.syntax`` for a visual, colorized diff display.
        """
        content = event["content"]
        is_error = event["is_error"]

        # Check for a diff section in the result content
        diff_marker = "\nDiff:\n"
        diff_idx = content.find(diff_marker)

        if not is_error and diff_idx != -1:
            # Split into summary (before Diff:) and diff body (after)
            summary = content[:diff_idx].strip()
            diff_text = content[diff_idx + len(diff_marker):].strip()

            # Render the summary one-liner
            _console.print(
                f"  [dim green]→ {summary}[/]",
                highlight=False,
            )

            # Render the diff with syntax highlighting
            if diff_text:
                _console.print(
                    Syntax(
                        diff_text,
                        "diff",
                        theme="ansi_dark",
                        line_numbers=False,
                    )
                )
        else:
            # Fall back to the compact one-liner for non-diff results
            preview = content[:120].replace("\n", " ")
            if is_error:
                _console.print(f"  [red]✗ {preview}[/]", highlight=False)
            else:
                suffix = "…" if len(content) > 120 else ""
                _console.print(
                    f"  [dim green]→ {preview}{suffix}[/]",
                    highlight=False,
                )

    def _render_done(self, event: dict[str, Any]) -> None:
        """Response complete — flush remaining Markdown, show token usage."""
        if self._md is not None:
            self._md.flush_all()
        usage = event.get("usage")
        if usage is not None:
            _console.print(
                f"\n[dim]📊 {usage['prompt_tokens']}↑"
                f" {usage['completion_tokens']}↓"
                f" {usage['total_tokens']}∑[/]"
            )

    def _render_cancelled(self) -> None:
        """Render a cancellation notice."""
        stop_spinner()
        if not self.content_started and not self.thinking_emitted:
            _console.print("\n[dim](empty response)[/]")
        elif self.content_started:
            _console.print()
        _console.print("\n[dim](cancelled)[/]")

    def _render_error(self, event: dict[str, Any]) -> None:
        """Render an error message."""
        stop_spinner()
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


def set_markdown_mode(enabled: bool = True) -> None:
    """Toggle Markdown rendering for future turns.

    Recreates the singleton renderer with the new setting.
    Call before a turn starts for best results.
    """
    global _renderer  # noqa: PLW0603
    _renderer = EventRenderer(use_markdown=enabled)
    _renderer.reset()

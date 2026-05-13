"""Two-pane TUI for the MVA REPL using prompt-toolkit.

Provides :class:`TUIApplication` — a full-screen prompt-toolkit
``Application`` with a scrollable output pane (top) and a multi-line
input pane (bottom).  No ANSI scrollback pollution because all content
lives inside prompt-toolkit's own in-memory buffers.

Usage from the REPL loop::

    tui = TUIApplication(completer=..., bottom_toolbar=..., style=..., history=...)
    asyncio.run(_repl_async(tui, ...))

Inside the async REPL::

    while True:
        user_input = await tui.get_input()   # blocks until submit
        if user_input is None:               # EOF → exit
            break
        tui.append_output(f"You: {user_input}")
        # ... stream events to tui ...
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Callable

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.widgets import TextArea

# ---------------------------------------------------------------------------
# Rich markup stripper for status bar text
# ---------------------------------------------------------------------------


def _plain_status(text: str) -> str:
    """Strip rich markup tags from *text* for prompt-toolkit status bar.

    Rich uses ``[tag]...[/]`` syntax for markup.  Prompt-toolkit's
    status bar doesn't understand it, so we strip these tags.

    Handles ``[dim]``, ``[/]``, ``[bold green]``, etc.
    """
    return re.sub(r"\[/?[^\]]*\]", "", text)

# ---------------------------------------------------------------------------
# TUIApplication
# ---------------------------------------------------------------------------


class TUIApplication:
    """Two-pane TUI: scrollable output (top) + input prompt (bottom).

    Parameters
    ----------
    completer:
        A :class:`~prompt_toolkit.completion.Completer` for the input pane.
    bottom_toolbar:
        A callable returning the toolbar text (or a static string).
    style:
        A :class:`~prompt_toolkit.styles.Style` instance.
    history:
        A :class:`~prompt_toolkit.history.History` instance for input recall.
    """

    def __init__(
        self,
        *,
        completer: Completer,
        bottom_toolbar: Callable[[], str],
        style: PTStyle,
        history: FileHistory,
    ) -> None:
        self._submit_future: asyncio.Future[str | None] | None = None

        # ------------------------------------------------------------------
        # Output pane — TextArea with scrollbar, read-only.
        # Stores plain text; no ANSI pollution in terminal scrollback.
        # ------------------------------------------------------------------
        self._output_area = TextArea(
            text="",
            read_only=True,
            scrollbar=True,
            wrap_lines=True,
            style="class:output-pane",
        )
        self.output_pane = self._output_area.window

        # ------------------------------------------------------------------
        # Input pane — Buffer-based for full control over key bindings.
        # We wrap it in a Window to control the height.
        # ------------------------------------------------------------------
        self._input_buffer = Buffer(
            completer=completer,
            history=history,
            multiline=True,
            accept_handler=self._on_accept,
        )
        self._input_control = BufferControl(
            buffer=self._input_buffer,
            focusable=True,
        )
        self._input_window = Window(
            content=self._input_control,
            wrap_lines=True,
            height=Dimension(min=3, max=8),
            style="class:input-pane",
        )

        # ------------------------------------------------------------------
        # Status bar — dynamic text from the *bottom_toolbar* callable.
        # Must be a callable returning ``FormattedText``.
        # ------------------------------------------------------------------
        self._status_control = FormattedTextControl(
            text=lambda: _plain_status(bottom_toolbar()),
        )
        status_bar = Window(
            content=self._status_control,
            height=Dimension.exact(1),
            style="class:status-bar",
            always_hide_cursor=True,
        )

        # ------------------------------------------------------------------
        # Layout: output pane (grows) / separator / input pane (fixed height)
        #          / status bar (fixed height)
        # ------------------------------------------------------------------
        separator = Window(
            height=Dimension.exact(1),
            char="─",
            style="class:separator",
        )

        root = HSplit(
            [
                self._output_area,  # TextArea includes its own window
                separator,
                self._input_window,
                status_bar,
            ]
        )

        # ------------------------------------------------------------------
        # Key bindings
        # ------------------------------------------------------------------
        kb = KeyBindings()
        self._add_key_bindings(kb)

        # ------------------------------------------------------------------
        # Application
        # ------------------------------------------------------------------
        self._app = Application(
            layout=Layout(root, focused_element=self._input_buffer),
            key_bindings=kb,
            style=style,
            mouse_support=True,
            full_screen=True,
        )

    # ------------------------------------------------------------------
    # Public API — used by the REPL loop
    # ------------------------------------------------------------------

    async def get_input(self) -> str | None:
        """Wait for the user to submit input.

        Returns the submitted text (possibly empty), or ``None`` when
        the user sends EOF (Ctrl+D) or exit (Ctrl+C on empty buffer).
        """
        self._submit_future = asyncio.get_event_loop().create_future()
        result = await self._submit_future
        return result

    async def run_async(self) -> None:
        """Run the application event loop."""
        await self._app.run_async()

    def exit(self) -> None:
        """Exit the application."""
        self._app.exit()

    def invalidate(self) -> None:
        """Request a UI refresh."""
        self._app.invalidate()

    # ------------------------------------------------------------------
    # Output management
    # ------------------------------------------------------------------

    def append_output(self, text: str) -> None:
        """Append *text* as a new line to the output pane."""
        current = self._output_area.text
        if current:
            self._output_area.text = current + "\n" + text
        else:
            self._output_area.text = text
        self._scroll_to_bottom()

    def append_raw(self, text: str) -> None:
        """Append *text* inline (no trailing newline)."""
        self._output_area.text += text
        self.invalidate()

    def clear_output(self) -> None:
        """Clear all output."""
        self._output_area.text = ""
        self.invalidate()

    def set_output_text(self, text: str) -> None:
        """Replace the entire output pane with *text*."""
        self._output_area.text = text
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        """Scroll the output pane to show the latest content."""
        buf = self._output_area.buffer
        buf.cursor_position = len(self._output_area.text)
        self.invalidate()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_accept(self, buf: Buffer) -> bool:
        """Accept handler — called when input is submitted.

        Stores the text, clears the buffer, and resolves the pending
        future so that ``get_input()`` can return.
        """
        text = buf.text
        buf.text = ""

        if self._submit_future is not None and not self._submit_future.done():
            self._submit_future.set_result(text)
        return False  # Don't let the buffer accept (we cleared it)

    def _add_key_bindings(self, kb: KeyBindings) -> None:
        """Register key bindings for the TUI."""

        @kb.add("enter")
        def _enter(event: Any) -> None:
            """Submit on empty line; insert newline otherwise.

            Commands starting with ``/`` submit immediately on single Enter.
            Regular messages require double-Enter (empty line to confirm).
            """
            buf = event.current_buffer
            text = buf.text

            if not text:
                # Empty buffer → submit (REPL loop strips empties)
                buf.validate_and_handle()
            elif text.strip().startswith("/"):
                # Commands submit immediately on single Enter
                buf.validate_and_handle()
            elif text.endswith("\n"):
                # Buffer ends with newline → cursor on empty line → submit
                buf.validate_and_handle()
            else:
                # Non-empty line → insert newline
                buf.insert_text("\n")

        @kb.add("c-c")
        def _cancel(event: Any) -> None:
            """Cancel current input (returns empty string)."""
            if self._submit_future is not None and not self._submit_future.done():
                self._submit_future.set_result("")

        @kb.add("c-d")
        def _eof(event: Any) -> None:
            """Exit on EOF."""
            if self._submit_future is not None and not self._submit_future.done():
                self._submit_future.set_result(None)

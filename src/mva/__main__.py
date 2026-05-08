"""Simple interactive CLI chatbot with streaming and thinking-trace display."""

from __future__ import annotations

import sys

from mva.utils import (
    DEFAULT_SYSTEM_PROMPT,
    build_messages,
    goodbye,
    handle_command,
    install_signal_handler,
    print_header,
)
from mva.llm import ChatMessage, LLMClient, LLMError
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

_console = Console()


def app() -> None:
    """Entry point for ``python -m mva``."""

    install_signal_handler()
    print_header()

    client = LLMClient()
    history: list[dict[str, str]] = []

    try:
        _repl(client, history)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


def _repl(client: LLMClient, history: list[dict[str, str]]) -> None:
    while True:
        try:
            raw = _console.input("[bold green]You:[/] ")
        except (EOFError, KeyboardInterrupt):
            break

        raw = raw.strip()
        if not raw:
            continue

        # Commands start with '/'
        if raw.startswith("/"):
            result = handle_command(raw, history, client)
            if result is False:
                break
            continue

        # --- Regular message ---
        messages = build_messages(DEFAULT_SYSTEM_PROMPT, history, raw)

        # Streaming response
        try:
            _stream_response(client, messages)
        except LLMError as exc:
            _console.print(f"\n[red]Error:[/] {exc}")
            continue

        print()


def _stream_response(client: LLMClient, messages: list[ChatMessage]) -> None:
    """Stream a chat response, rendering thinking and content in real-time."""

    thinking_emitted = False
    content_started = False

    for delta in client.chat_stream(messages):
        # --- Thinking / reasoning ---
        if delta.thinking and not thinking_emitted:
            thinking_emitted = True
            _console.print("\n[bold dim]Thinking[/]", highlight=False)

        if delta.thinking_delta:
            _console.print(
                f"[dim italic]{delta.thinking_delta}[/]",
                end="",
                highlight=False,
            )

        # --- Regular content ---
        if delta.delta:
            if not content_started:
                content_started = True
                if thinking_emitted:
                    # Close thinking section before starting response
                    _console.print("---")
                _console.print("\n[bold cyan]Assistant:[/] ", end="", highlight=False)

            _console.print(delta.delta, end="", highlight=False)

    if not content_started and not thinking_emitted:
        _console.print("\n[dim](empty response)[/]")
    elif not content_started and thinking_emitted:
        # Thinking-only response
        pass
    else:
        _console.print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()

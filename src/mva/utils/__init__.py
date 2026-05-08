"""UI helpers for the mva chatbot TUI."""

from __future__ import annotations

import os
import signal
import sys
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from mva.llm import ChatMessage, LLMClient

_console = Console()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = os.getenv(
    "MVA_SYSTEM_PROMPT",
    "You are a helpful, concise assistant. Answer the user's questions clearly "
    "and accurately.",
)


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def install_signal_handler() -> None:
    signal.signal(signal.SIGINT, _signal_handler)


def _signal_handler(signum: int, _frame: Any) -> None:
    print()
    goodbye()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def print_header() -> None:
    table = Table.grid(padding=0)
    table.add_column(justify="center")
    table.add_row("[bold blue]MVA Chatbot[/]")
    table.add_row("[dim]Powered by OpenAI-compatible API[/]")
    _console.print(Panel(table, border_style="blue", padding=(1, 2)))


def goodbye() -> None:
    print()
    _console.print("[dim]Goodbye![/]")


def print_help() -> None:
    table = Table(title="Commands", title_style="bold", box=None)
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="white")
    table.add_row("/exit, /quit", "Exit the chatbot")
    table.add_row("/clear, /reset", "Clear conversation history")
    table.add_row("/help", "Show this help message")
    table.add_row("/history", "Show recent conversation history")
    _console.print(table)


# ---------------------------------------------------------------------------
# Message construction (chat completions format)
# ---------------------------------------------------------------------------


def build_messages(
    system: str, history: list[dict[str, str]], new_user_msg: str
) -> list[ChatMessage]:
    """Build a message list suitable for the chat completions API."""
    messages: list[ChatMessage] = []

    if system:
        messages.append(ChatMessage(role="system", content=system))

    for turn in history:
        role = turn["role"]
        content = turn["content"]
        messages.append(ChatMessage(role=role, content=content))

    messages.append(ChatMessage(role="user", content=new_user_msg))
    return messages


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------


def handle_command(
    raw: str, history: list[dict[str, str]], client: LLMClient
) -> bool | None:
    cmd = raw[1:].lower().strip()

    if cmd in ("exit", "quit", "q"):
        goodbye()
        return False

    if cmd in ("clear", "cls", "reset"):
        history.clear()
        _console.print("[dim]Conversation cleared.[/]")
        return True

    if cmd == "help":
        print_help()
        return True

    if cmd == "history":
        if not history:
            _console.print("[dim]No conversation history.[/]")
            return True
        for i, turn in enumerate(history):
            role = turn["role"]
            content = turn["content"][:200]
            style = "green" if role == "user" else "cyan"
            _console.print(f"  [{style}]{i+1}. {role}:[/] {content}")
        return True

    _console.print(f"[yellow]Unknown command:[/] {raw}")
    _console.print("Type [bold]/help[/] for available commands.")
    return True

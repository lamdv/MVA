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

from mva.llm import ChatMessage, LLMClient, ToolDef
from mva.tools import execute_tool, get_tool_defs

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
    table.add_row("/tools", "List available tools")
    _console.print(table)


# ---------------------------------------------------------------------------
# System prompt (tool-aware)
# ---------------------------------------------------------------------------


def build_system_prompt(tools: list[ToolDef] | None = None) -> str:
    """Build a system prompt, optionally including tool instructions.

    When tools are provided, the system prompt includes instructions on how
    to use them, following conventions inspired by the pi coding agent.
    """
    prompt = DEFAULT_SYSTEM_PROMPT

    if tools:
        tool_descriptions = "\n".join(
            f"- **{t.name}**: {t.description}" for t in tools
        )
        tool_names = ", ".join(f"`{t.name}`" for t in tools)

        prompt += f"""

You have access to the following tools:

{tool_descriptions}

## How to use tools

When you need to read a file, write a file, list directory contents, or execute
a bash command, call the appropriate tool. The user cannot see your tool calls —
they only see your final response. Execute tools proactively when they would help
answer the user's request.

**Important tool usage rules:**

- Use the `read` tool to read file contents. Always specify the exact path.
- Use the `write` tool to create or overwrite files. Parent directories are created
  automatically.
- Use the `list_files` (or `ls`) tool to list directory contents. The `depth`
  parameter controls recursion depth.
- Use the `bash` tool to execute shell commands. The command runs in the current
  working directory. Output is truncated to the last 2000 lines or 50KB.

When you receive tool results, incorporate them into your response naturally.
If a tool returns an error, explain the error to the user and suggest alternatives.
"""
    return prompt


# ---------------------------------------------------------------------------
# Message construction (chat completions format)
# ---------------------------------------------------------------------------


def build_messages(
    system: str, history: list[dict[str, Any]], new_user_msg: str
) -> list[ChatMessage]:
    """Build a message list suitable for the chat completions API.

    Handles regular user/assistant messages as well as tool-call and
    tool-result messages in the history.
    """
    messages: list[ChatMessage] = []

    if system:
        messages.append(ChatMessage(role="system", content=system))

    for turn in history:
        role = turn["role"]
        content = turn.get("content", "")

        if role == "tool":
            messages.append(ChatMessage(
                role="tool",
                content=str(content),
                tool_call_id=turn.get("tool_call_id", ""),
            ))
        elif role == "assistant" and turn.get("tool_calls"):
            messages.append(ChatMessage(
                role="assistant",
                content=content or "",
                tool_calls=turn["tool_calls"],
            ))
        else:
            messages.append(ChatMessage(role=role, content=content))

    messages.append(ChatMessage(role="user", content=new_user_msg))
    return messages


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------


def handle_command(
    raw: str, history: list[dict[str, Any]], client: LLMClient
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

    if cmd == "tools":
        _print_tools()
        return True

    if cmd == "history":
        if not history:
            _console.print("[dim]No conversation history.[/]")
            return True
        for i, turn in enumerate(history):
            role = turn["role"]
            content = turn.get("content", "")[:200]
            style = "green" if role == "user" else "cyan"
            extra = ""
            if turn.get("tool_calls"):
                names = [tc["function"]["name"] for tc in turn["tool_calls"]]
                extra = f" [yellow][tool_calls: {', '.join(names)}][/]"
            if role == "tool":
                extra = f" [magenta][tool_result][/]"
            _console.print(f"  [{style}]{i+1}. {role}:[/] {content}{extra}")
        return True

    _console.print(f"[yellow]Unknown command:[/] {raw}")
    _console.print("Type [bold]/help[/] for available commands.")
    return True


def _print_tools() -> None:
    """Print the list of available tools."""
    tools = get_tool_defs()
    if not tools:
        _console.print("[dim]No tools available.[/]")
        return
    table = Table(title="Available Tools", title_style="bold", box=None)
    table.add_column("Tool", style="cyan")
    table.add_column("Description", style="white")
    for t in tools:
        table.add_row(t.name, t.description)
    _console.print(table)

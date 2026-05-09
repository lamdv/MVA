from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from mva.utils import (
    build_messages,
    build_system_prompt,
    goodbye,
    handle_command,
    install_signal_handler,
    print_header,
)
from mva.llm import ChatMessage, LLMClient, LLMError, StreamingDelta, ToolDef
from mva.skills import SkillDef, discover_skills
from mva.tools import ToolResult, execute_tool, get_tool_defs
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

_console = Console()

MAX_TOOL_ROUNDS = 10  # safety limit for tool call loops

# ---------------------------------------------------------------------------
# CLI application
# ---------------------------------------------------------------------------

_app = typer.Typer(
    name="mva",
    help="MVA — Minimum Viable Agent harness.",
    add_completion=False,
)


@_app.command()
def app(
    message: Annotated[
        list[str] | None,
        typer.Argument(help="Task to run (non-interactive when provided)."),
    ] = None,
    print_mode: Annotated[
        bool,
        typer.Option(
            "--print",
            "-p",
            help="Print response and exit (non-interactive).",
        ),
    ] = False,
    system_prompt: Annotated[
        str | None,
        typer.Option("--system-prompt", help="Replace the default system prompt."),
    ] = None,
    append_system_prompt: Annotated[
        str | None,
        typer.Option(
            "--append-system-prompt", help="Append text to the system prompt."
        ),
    ] = None,
    skill: Annotated[
        list[str] | None,
        typer.Option(
            "--skill",
            "-s",
            help="Load a skill from a directory or SKILL.md file (repeatable).",
        ),
    ] = None,
    no_skills: Annotated[
        bool,
        typer.Option("--no-skills", help="Disable all skill loading."),
    ] = False,
    no_context_files: Annotated[
        bool,
        typer.Option(
            "--no-context-files",
            "-nc",
            help="Disable AGENT.md context file loading.",
        ),
    ] = False,
) -> None:
    """Launch the MVA interactive REPL, or run a single task non-interactively."""

    install_signal_handler()

    # Discover skills at startup
    skills = discover_skills(
        extra_dirs=skill,
        no_skills=no_skills,
    )

    # Build the user message: CLI argument(s) + optional piped stdin
    user_message = " ".join(message) if message else ""
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            user_message = f"{piped}\n\n{user_message}" if user_message else piped
    user_message = user_message.strip()

    client = LLMClient()
    agent_md_path: str | None = None if no_context_files else "AGENT.md"

    try:
        if print_mode or message:
            # Non-interactive single-run mode
            _run_single(
                client,
                user_message,
                skills,
                system_prompt=system_prompt,
                append_system_prompt=append_system_prompt,
                agent_md_path=agent_md_path,
            )
        else:
            # Interactive REPL
            print_header(skills=skills if skills else None)
            history: list[dict[str, Any]] = []
            _repl(
                client,
                history,
                skills,
                system_prompt=system_prompt,
                append_system_prompt=append_system_prompt,
                agent_md_path=agent_md_path,
            )
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Single-run (print) mode
# ---------------------------------------------------------------------------


def _run_single(
    client: LLMClient,
    user_message: str,
    skills: list[SkillDef],
    *,
    system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    agent_md_path: str | None = "AGENT.md",
) -> None:
    """Run a single task non-interactively and print the result."""
    if not user_message:
        _console.print("[red]Error:[/] No message provided.")
        raise typer.Exit(code=1)

    tools = get_tool_defs()
    system = build_system_prompt(
        tools,
        skills=skills,
        agent_md_path=agent_md_path,
        system_prompt=system_prompt,
        append_system_prompt=append_system_prompt,
    )

    history: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    messages = build_messages(system, history, "")
    messages = [m for m in messages if m.role != "user" or m.content]

    try:
        _handle_turn(
            client,
            messages,
            tools,
            history,
            skills,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
            agent_md_path=agent_md_path,
            print_mode=True,
        )
    except LLMError as exc:
        _console.print(f"\n[red]Error:[/] {exc}")
        raise typer.Exit(code=1)

    print()


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


def _repl(
    client: LLMClient,
    history: list[dict[str, Any]],
    skills: list[SkillDef],
    *,
    system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    agent_md_path: str | None = "AGENT.md",
) -> None:
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
            result = handle_command(raw, history, client, skills=skills)
            if result is False:
                break
            continue

        # --- Regular message ---
        tools = get_tool_defs()
        system = build_system_prompt(
            tools,
            skills=skills,
            agent_md_path=agent_md_path,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
        )

        # Record the user message in history *before* the turn,
        # so it appears in the log and in future conversation context.
        history.append({"role": "user", "content": raw})
        messages = build_messages(system, history, "")
        # Drop the trailing empty user message added by build_messages
        messages = [m for m in messages if m.role != "user" or m.content]

        # Tool calling loop: keep sending tool results until the model
        # responds with text instead of tool calls.
        try:
            _handle_turn(
                client,
                messages,
                tools,
                history,
                skills,
                system_prompt=system_prompt,
                append_system_prompt=append_system_prompt,
                agent_md_path=agent_md_path,
            )
        except LLMError as exc:
            _console.print(f"\n[red]Error:[/] {exc}")
            continue

        print()


# ---------------------------------------------------------------------------
# Turn handler with tool calling loop
# ---------------------------------------------------------------------------


def _handle_turn(
    client: LLMClient,
    messages: list[ChatMessage],
    tools: list[ToolDef],
    history: list[dict[str, Any]],
    skills: list[SkillDef],
    *,
    system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    agent_md_path: str | None = "AGENT.md",
    print_mode: bool = False,
) -> None:
    """Process a single user turn, including any tool call round-trips."""
    rounds = 0

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1
        final_tool_calls: list[dict[str, Any]] | None = None
        final_delta: StreamingDelta | None = None

        # Stream response
        for delta in client.chat_stream(messages, tools=tools if tools else None):
            _render_delta(delta)
            if delta.tool_calls:
                final_tool_calls = delta.tool_calls
            final_delta = delta

        if (
            final_tool_calls
            and final_delta
            and final_delta.finish_reason == "tool_calls"
        ):
            # Model wants to call tools
            _console.print("\n[bold yellow]🔧 Calling tools…[/]")
            assistant_entry: dict[str, Any] = {
                "role": "assistant",
                "content": final_delta.accumulated or "",
                "tool_calls": final_tool_calls,
                "reasoning_content": final_delta.reasoning_content,
            }
            history.append(assistant_entry)

            # Execute each tool call
            for tc in final_tool_calls:
                tc_id = tc.get("id", "")
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]
                if isinstance(fn_args, str):
                    try:
                        fn_args = json.loads(fn_args)
                    except json.JSONDecodeError:
                        fn_args = {}

                _console.print(
                    f"  [dim]{fn_name}({json.dumps(fn_args)})[/]",
                    highlight=False,
                )

                result = _execute_tool_with_confirmation(
                    fn_name, fn_args, print_mode=print_mode
                )

                if not print_mode:
                    if result.is_error:
                        _console.print(f"  [red]✗ {result.content[:120]}[/]")
                    else:
                        preview = result.content[:120].replace("\n", " ")
                        _console.print(
                            f"  [dim green]→ {preview}…[/]"
                            if len(result.content) > 120
                            else f"  [dim green]→ {preview}[/]"
                        )

                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result.content,
                    }
                )

            # Rebuild messages with new history for next round
            messages = build_messages(
                build_system_prompt(
                    tools,
                    skills=skills,
                    agent_md_path=agent_md_path,
                    system_prompt=system_prompt,
                    append_system_prompt=append_system_prompt,
                ),
                history,
                "",  # no new user message, continue tool loop
            )
            # Remove the trailing empty user message added by build_messages
            messages = [m for m in messages if m.role != "user" or m.content]
            continue

        # Model responded with text — done
        if final_delta and (final_delta.accumulated or final_delta.reasoning_content):
            history.append(
                {
                    "role": "assistant",
                    "content": final_delta.accumulated,
                    "reasoning_content": final_delta.reasoning_content,
                }
            )
        return

    # Safety limit reached
    msg = "⚠ Max tool-calling rounds reached. Stopping."
    if print_mode:
        sys.stdout.write(f"\n[{msg}]\n")
    else:
        _console.print(f"\n[red]{msg}[/]")
    history.append(
        {
            "role": "assistant",
            "content": "I've reached the tool-calling limit. Please ask a simpler question.",
        }
    )


# ---------------------------------------------------------------------------
# Tool execution with confirmation prompt
# ---------------------------------------------------------------------------


def _execute_tool_with_confirmation(
    fn_name: str,
    fn_args: dict[str, Any],
    *,
    print_mode: bool = False,
) -> ToolResult:
    """Execute a tool, handling ``needs_confirmation`` with user prompt loop.

    In *print_mode*, confirmations are auto-denied (no interactive user).
    """
    result = execute_tool(fn_name, fn_args)

    while result.needs_confirmation:
        if print_mode:
            msg = result.confirmation_message.split("\n")[0]
            return ToolResult(
                content=f"Blocked (print mode): {msg}",
                is_error=True,
            )
        _console.print()
        _console.print(
            Panel(
                result.confirmation_message,
                title="[bold yellow]⚠️  Security Check[/]",
                border_style="yellow",
            )
        )
        try:
            answer = _console.input("  Proceed? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer in ("y", "yes"):
            result = execute_tool(
                result.confirmation_tool,
                result.confirmation_args,
                confirmed=True,
            )
        else:
            msg = result.confirmation_message.split("\n")[0]
            result = ToolResult(
                content=f"Blocked by user: {msg}",
                is_error=True,
            )

    return result


# ---------------------------------------------------------------------------
# Streaming renderer
# ---------------------------------------------------------------------------


def _render_delta_plain(delta: StreamingDelta) -> None:
    """Render a streaming delta chunk in plain mode (just the text)."""
    if delta.tool_calls:
        return
    if delta.delta:
        sys.stdout.write(delta.delta)
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Streaming renderer
# ---------------------------------------------------------------------------


def _render_delta(delta: StreamingDelta) -> None:
    """Render a streaming delta chunk to the console."""

    # Track state via function attributes (simple approach)
    if not hasattr(_render_delta, "thinking_emitted"):
        _render_delta.thinking_emitted = False
    if not hasattr(_render_delta, "content_started"):
        _render_delta.content_started = False

    if delta.tool_calls:
        # When tool calls are being streamed, reset state for next turn
        _render_delta.thinking_emitted = False
        _render_delta.content_started = False
        return

    # --- Thinking / reasoning ---
    if delta.thinking and not _render_delta.thinking_emitted:
        _render_delta.thinking_emitted = True
        _console.print("\n[bold dim]Thinking…[/]", highlight=False)

    if delta.thinking_delta:
        _console.print(
            f"[dim italic]{delta.thinking_delta}[/]",
            end="",
            highlight=False,
        )

    # --- Regular content ---
    if delta.delta:
        if not _render_delta.content_started:
            _render_delta.content_started = True
            if _render_delta.thinking_emitted:
                _console.print()
            _console.print("\n[bold cyan]Assistant:[/] ", end="", highlight=False)

        _console.print(delta.delta, end="", highlight=False)

    # Reset on finish
    if delta.finish_reason:
        if not _render_delta.content_started and not _render_delta.thinking_emitted:
            _console.print("\n[dim](empty response)[/]")
        elif _render_delta.content_started:
            _console.print()

        _render_delta.thinking_emitted = False
        _render_delta.content_started = False


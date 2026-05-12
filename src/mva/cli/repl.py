"""MVA REPL loop — thin UI over :class:`mva.agent.Session`.

No longer owns history or the tool-calling loop — that lives in
:class:`Session`.  This module just handles input, rendering, and
commands.
"""

from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from mva.cli.renderer import render_event, reset_renderer, start_spinner, stop_spinner
from mva.agent import LLMError, Session, SkillDef, get_tool_defs
from mva.agent._system import build_system_prompt
from mva.cli._commands import (
    _save_session,
    goodbye,
    handle_command,
    print_header,
    reload_environment,
    _RELOAD_SENTINEL,
)

_console = Console()

# ---------------------------------------------------------------------------
# Model context display
# ---------------------------------------------------------------------------

_last_model_context: str = ""


def _show_model_context(session: Session) -> None:
    """Show the current model/provider + cumulative token usage."""
    global _last_model_context  # noqa: PLW0603
    prov = session.current_provider or "?"
    model = session.client.default_model or ""
    ctx = f"[dim]⚡ {prov}"
    if model:
        ctx += f" / {model}"
    usage = session.total_usage
    if usage and usage.total_tokens > 0:
        ctx += f"  │  📊 {usage.total_tokens}∑[/]"
    else:
        ctx += "[/]"
    if ctx != _last_model_context:
        _console.print(ctx)
        _last_model_context = ctx


# ---------------------------------------------------------------------------
# Confirmation callback
# ---------------------------------------------------------------------------


def _confirm_callback(message: str, tool: str, args: dict[str, Any]) -> bool:
    """Prompt the user for security confirmation.  Called by :class:`Session`."""
    _console.print()
    _console.print(
        Panel(
            message,
            title="[bold yellow]⚠️  Security Check[/]",
            border_style="yellow",
        )
    )
    try:
        answer = input("  Proceed? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    return answer in ("y", "yes")


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


def _repl(
    pt_session: PromptSession,
    session: Session,
    skills: list[SkillDef],
    *,
    system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    agent_md_path: str | None = "AGENT.md",
    auto_confirm: bool = False,
) -> None:
    """Interactive REPL: read-eval-print loop for the MVA agent."""
    session.on_confirm = _confirm_callback
    while True:
        try:
            raw = pt_session.prompt("You: ")
        except (EOFError, KeyboardInterrupt):
            if session.history:
                sid = _save_session(session.history, session)
                _console.print(f"[dim]💾 Auto-saved. Load with: /load {sid}[/]")
            goodbye()
            break

        raw = raw.strip()
        if not raw:
            continue

        # Commands start with '/'
        if raw.startswith("/"):
            result = handle_command(raw, session.history, session, skills=skills)
            if result is False:
                if session.history:
                    sid = _save_session(session.history, session)
                    _console.print(f"[dim]💾 Auto-saved. Load with: /load {sid}[/]")
                break
            if result is _RELOAD_SENTINEL:
                reload_environment(session, skills)
                # Rebuild the system prompt immediately so the next
                # message uses the freshly reloaded tools + skills
                session.system_prompt = build_system_prompt(
                    get_tool_defs(),
                    skills=skills,
                    agent_md_path=agent_md_path,
                    system_prompt=system_prompt,
                    append_system_prompt=append_system_prompt,
                )
                _console.print(
                    "[dim]System prompt updated with reloaded tools"
                    " and skills.[/]"
                )
            continue

        # Show current model/provider as a subtle reminder
        _show_model_context(session)

        # Build system prompt (fresh every turn for skill/AGENT.md changes)
        session.system_prompt = build_system_prompt(
            get_tool_defs(),
            skills=skills,
            agent_md_path=agent_md_path,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
        )

        reset_renderer()

        try:
            start_spinner()
            for event in session.chat(raw, auto_confirm=auto_confirm):
                render_event(event)
        except LLMError as exc:
            stop_spinner()
            _console.print(f"\n[red]Error:[/] {exc}")
            # Strip the failed user message from history so the
            # model doesn't see it again on the next attempt
            if session.history and session.history[-1]["role"] == "user":
                session.history.pop()
            _console.print("[dim]Message discarded. Re-type it or try something else.[/]")
            continue

        print()


# ---------------------------------------------------------------------------
# Single-run (non-interactive)
# ---------------------------------------------------------------------------


def _run_single(
    user_message: str,
    skills: list[SkillDef],
    *,
    system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    agent_md_path: str | None = "AGENT.md",
    max_tool_rounds: int = 10,
    auto_confirm: bool = False,
) -> str | None:
    """Run a single task non-interactively.

    Returns the final response text, or ``None`` on error.
    """
    if not user_message:
        _console.print("[red]Error:[/] No message provided.")
        return None

    tools = get_tool_defs()
    system = build_system_prompt(
        tools,
        skills=skills,
        agent_md_path=agent_md_path,
        system_prompt=system_prompt,
        append_system_prompt=append_system_prompt,
    )

    session = Session(
        tools=tools,
        system_prompt=system,
        on_confirm=None,  # auto-deny in print mode
        max_tool_rounds=max_tool_rounds,
    )

    try:
        final_text = ""
        start_spinner()
        for event in session.chat(
            user_message, print_mode=(not auto_confirm), auto_confirm=auto_confirm
        ):
            if event.get("type") == "done":
                final_text = event.get("content", "")
            # Print streaming content directly
            if event.get("type") == "thinking":
                _console.print(f"[dim italic]{event['content']}[/]", end="")
            elif event.get("type") == "delta":
                _console.print(event["content"], end="")
            elif event.get("type") == "tool_call":
                stop_spinner()
                print()
                _console.print(f"  [dim]{event['name']}({event['args']})[/]")
            elif event.get("type") == "tool_result":
                content = event["content"]
                is_error = event["is_error"]
                # Check for diff section
                diff_marker = "\nDiff:\n"
                diff_idx = content.find(diff_marker)
                if not is_error and diff_idx != -1:
                    summary = content[:diff_idx].strip()
                    diff_text = content[diff_idx + len(diff_marker):].strip()
                    _console.print(f"  [dim green]→ {summary}[/]")
                    if diff_text:
                        _console.print(
                            Syntax(diff_text, "diff", theme="ansi_dark", line_numbers=False)
                        )
                else:
                    preview = content[:80].replace("\n", " ")
                    if is_error:
                        _console.print(f"  [red]✗ {preview}[/]")
                    else:
                        _console.print(f"  [dim green]→ {preview}…[/]")
        return final_text
    except LLMError as exc:
        stop_spinner()
        _console.print(f"\n[red]Error:[/] {exc}")
        return None

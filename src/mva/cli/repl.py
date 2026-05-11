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

from mva.cli.renderer import render_event, reset_renderer
from mva.agent import LLMClient, LLMError, Session, SkillDef, get_tool_defs
from mva.utils import (
    build_system_prompt,
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


def _show_model_context(client: LLMClient) -> None:
    """Show the current model/provider as a subtle one-liner (when it changes)."""
    global _last_model_context  # noqa: PLW0603
    prov = client.current_provider or "?"
    model = client.default_model or ""
    ctx = f"[dim]⚡ {prov}"
    if model:
        ctx += f" / {model}"
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
    client: LLMClient,
    history: list[dict[str, Any]],
    agent_session: Session,
    skills: list[SkillDef],
    *,
    system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    agent_md_path: str | None = "AGENT.md",
) -> None:
    """Interactive REPL: read-eval-print loop for the MVA agent."""
    agent_session.on_confirm = _confirm_callback
    while True:
        try:
            raw = pt_session.prompt("You: ")
        except (EOFError, KeyboardInterrupt):
            goodbye()
            break

        raw = raw.strip()
        if not raw:
            continue

        # Commands start with '/'
        if raw.startswith("/"):
            result = handle_command(raw, history, client, skills=skills)
            if result is False:
                break
            if result is _RELOAD_SENTINEL:
                reload_environment(agent_session, skills)
                # Rebuild the system prompt immediately so the next
                # message uses the freshly reloaded tools + skills
                agent_session.system_prompt = build_system_prompt(
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
        _show_model_context(client)

        # Build system prompt (fresh every turn for skill/AGENT.md changes)
        agent_session.system_prompt = build_system_prompt(
            get_tool_defs(),
            skills=skills,
            agent_md_path=agent_md_path,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
        )

        reset_renderer()

        try:
            for event in agent_session.chat(raw):
                render_event(event)
        except LLMError as exc:
            _console.print(f"\n[red]Error:[/] {exc}")
            continue

        print()


# ---------------------------------------------------------------------------
# Single-run (non-interactive)
# ---------------------------------------------------------------------------


def _run_single(
    client: LLMClient,
    user_message: str,
    skills: list[SkillDef],
    *,
    system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    agent_md_path: str | None = "AGENT.md",
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

    agent_session = Session(
        client=client,
        tools=tools,
        system_prompt=system,
        on_confirm=None,  # auto-deny in print mode
    )

    try:
        final_text = ""
        for event in agent_session.chat(user_message, print_mode=True):
            if event.get("type") == "done":
                final_text = event.get("content", "")
            # Print streaming content directly
            if event.get("type") == "thinking":
                _console.print(f"[dim italic]{event['content']}[/]", end="")
            elif event.get("type") == "delta":
                _console.print(event["content"], end="")
            elif event.get("type") == "tool_call":
                print()
                _console.print(f"  [dim]{event['name']}({event['args']})[/]")
            elif event.get("type") == "tool_result":
                preview = event["content"][:80].replace("\n", " ")
                if event["is_error"]:
                    _console.print(f"  [red]✗ {preview}[/]")
                else:
                    _console.print(f"  [dim green]→ {preview}…[/]")
        return final_text
    except LLMError as exc:
        _console.print(f"\n[red]Error:[/] {exc}")
        return None

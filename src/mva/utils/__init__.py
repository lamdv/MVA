"""UI helpers for the mva chatbot TUI."""

from __future__ import annotations

import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from mva.agent import ChatMessage, LLMClient, ToolDef
from mva.skills import SkillDef, build_skills_prompt, discover_skills
from mva.tools import execute_tool, get_tool_defs

_console = Console()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert coding assistant operating inside MVA, a coding agent "
    "harness. You help users by reading files, executing commands, editing "
    "code, and writing new files."
)


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stream cancellation support
# ---------------------------------------------------------------------------

_streaming_active = False
_cancel_requested = False


def _mark_streaming_start() -> None:
    """Mark that a streaming response is in progress (called from CLI)."""
    global _streaming_active, _cancel_requested
    _streaming_active = True
    _cancel_requested = False


def _mark_streaming_stop() -> None:
    """Mark that streaming has ended."""
    global _streaming_active
    _streaming_active = False


def is_cancel_requested() -> bool:
    """Check whether the user has requested cancellation of the current stream."""
    return _cancel_requested


def install_signal_handler() -> None:
    signal.signal(signal.SIGINT, _signal_handler)


def _signal_handler(signum: int, _frame: Any) -> None:
    global _cancel_requested
    if _streaming_active:
        # During streaming: request cancellation instead of exiting.
        # The streaming loop will stop gracefully and return to the REPL.
        _cancel_requested = True
    else:
        # Idle / waiting for input: exit as before.
        goodbye(interrupted=True)
        sys.exit(0)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def print_header(*, skills: list[SkillDef] | None = None) -> None:
    table = Table.grid(padding=0)
    table.add_column(justify="center")
    table.add_row("[bold blue]MVA Chatbot[/]")
    table.add_row("[dim]Powered by OpenAI-compatible API[/]")
    if skills:
        loaded = sum(1 for s in skills if s.enabled)
        table.add_row(f"[dim]{loaded} of {len(skills)} skill(s) loaded[/]")
    _console.print(Panel(table, border_style="blue", padding=(1, 2)))


def goodbye(*, interrupted: bool = False) -> None:
    print()
    if interrupted:
        _console.print("[dim]Interrupted. Goodbye![/]")
    else:
        _console.print("[dim]Goodbye![/]")


def print_help() -> None:
    table = Table(title="Commands", title_style="bold", box=None)
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="white")
    table.add_row("/exit, /quit", "Exit the chatbot")
    table.add_row("/clear, /reset", "Clear conversation history")
    table.add_row("/help", "Show this help message")
    table.add_row("/history", "Show recent conversation history")
    table.add_row("/model", "Show current model and list available models")
    table.add_row("/model <name>", "Switch model within the current provider")
    table.add_row("/provider, /providers", "List available providers")
    table.add_row("/provider <name>", "Switch to a different provider")
    table.add_row("/tools", "List available tools")
    table.add_row("/skills", "List available skills")
    table.add_row("/skill:<name>", "Enable/disable a skill")
    _console.print(table)


# ---------------------------------------------------------------------------
# System prompt (tool-aware)
# ---------------------------------------------------------------------------


def _tool_snippet(t: ToolDef) -> str:
    """Extract a one-line snippet from a tool definition."""
    # Take the first sentence of the description
    desc = t.description
    # Cut at first period followed by space or end
    for cut in (". ", ".\n", ".  "):
        idx = desc.find(cut)
        if idx != -1:
            desc = desc[:idx + 1]
            break
    return desc


def _read_file(path: Path) -> str | None:
    """Read a file, returning its contents or ``None``."""
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _load_system_md() -> str | None:
    """Load a custom system prompt from ``SYSTEM.md``.

    Checks (in order, first wins):
    1. ``.mva/SYSTEM.md`` (project)
    2. ``~/.mva/SYSTEM.md`` (global)
    """
    project = Path.cwd() / ".mva" / "SYSTEM.md"
    content = _read_file(project)
    if content:
        return content
    return _read_file(Path.home() / ".mva" / "SYSTEM.md")


def _load_append_system_md() -> str | None:
    """Load append-only system prompt content from ``APPEND_SYSTEM.md``.

    Checks (in order):
    1. ``.mva/APPEND_SYSTEM.md`` (project)
    2. ``~/.mva/APPEND_SYSTEM.md`` (global)
    """
    project = Path.cwd() / ".mva" / "APPEND_SYSTEM.md"
    content = _read_file(project)
    if content:
        return content
    return _read_file(Path.home() / ".mva" / "APPEND_SYSTEM.md")


def _load_agent_md(path: str = "AGENT.md") -> str | None:
    """Read the AGENT.md file from CWD if it exists."""
    return _read_file(Path.cwd() / path)


def build_system_prompt(
    tools: list[ToolDef] | None = None,
    *,
    agent_md_path: str | None = "AGENT.md",
    skills: list[SkillDef] | None = None,
    system_prompt: str | None = None,
    append_system_prompt: str | None = None,
) -> str:
    """Build a system prompt, optionally including AGENT.md, skills, and tool instructions.

    Layers are assembled in order:

    1. Base prompt — first of: *system_prompt*, ``.mva/SYSTEM.md``,
       ``~/.mva/SYSTEM.md``, ``MVA_SYSTEM_PROMPT`` env var, or built-in default
    2. Append prompt — *append_system_prompt* + ``APPEND_SYSTEM.md`` files
    3. ``AGENT.md`` context (if present)
    4. Skills (enabled skills only)
    5. Tool instructions (if tools are provided)
    6. Current date and working directory

    When *agent_md_path* is set, the function attempts to read that file
    from the current working directory and injects its contents into the
    system prompt.  Pass ``None`` to skip this behaviour.

    When *skills* is provided, enabled skills are injected into the prompt.

    When *tools* are provided, the system prompt includes instructions on how
    to use them, following conventions inspired by the pi coding agent.
    """
    # -- Layer 1: base prompt ---------------------------------------------
    mva_env = os.environ.get("MVA_SYSTEM_PROMPT", "").strip()
    prompt = (
        system_prompt
        or _load_system_md()
        or (mva_env if mva_env else None)
        or DEFAULT_SYSTEM_PROMPT
    )

    # -- Layer 2: append prompt -------------------------------------------
    append_text = ""
    if append_system_prompt:
        append_text += append_system_prompt
    append_md = _load_append_system_md()
    if append_md:
        if append_text:
            append_text += "\n\n"
        append_text += append_md
    if append_text:
        prompt += f"\n\n{append_text}"

    # -- Inject AGENT.md if present ---------------------------------------
    if agent_md_path:
        agent_md = _load_agent_md(agent_md_path)
        if agent_md:
            prompt += f"\n\n## Project context (from {agent_md_path})\n\n{agent_md}"

    # -- Inject skills ----------------------------------------------------
    if skills:
        skills_text = build_skills_prompt(skills)
        if skills_text:
            prompt += f"\n\n{skills_text}"

    if tools:
        # Short one-line snippets per tool
        tool_lines = "\n".join(
            f"- {t.name}: {_tool_snippet(t)}" for t in tools
        )

        prompt += f"""

Available tools:
{tool_lines}

Guidelines:
- Use bash for file operations like ls, rg, find
- Use read to examine files instead of cat or sed
- Use write for new files or complete rewrites
- Be concise in your responses
- Show file paths clearly when working with files
"""

    # -- Layer 6: date and working directory ------------------------------
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt += f"\nCurrent date: {now}"
    prompt += f"\nCurrent working directory: {Path.cwd()}"

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
                reasoning_content=turn.get("reasoning_content"),
            ))
        elif role == "assistant":
            messages.append(ChatMessage(
                role="assistant",
                content=content,
                reasoning_content=turn.get("reasoning_content"),
            ))
        else:
            messages.append(ChatMessage(role=role, content=content))

    messages.append(ChatMessage(role="user", content=new_user_msg))
    return messages


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------


def handle_command(
    raw: str,
    history: list[dict[str, Any]],
    client: LLMClient,
    *,
    skills: list[SkillDef] | None = None,
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

    if cmd == "model":
        _print_model_info(client)
        return True

    if cmd.startswith("model "):
        _switch_model(client, cmd[6:].strip())
        return True

    if cmd in ("provider", "providers"):
        _list_providers(client)
        return True

    if cmd.startswith("provider "):
        _switch_provider(client, cmd[9:].strip())
        return True

    if cmd == "tools":
        _print_tools()
        return True

    if cmd == "skills":
        _print_skills(skills or [])
        return True

    # /skill:name — toggle a skill
    if cmd.startswith("skill:"):
        skill_name = cmd[6:].strip()
        _toggle_skill(skills or [], skill_name)
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


def _print_skills(skills: list[SkillDef]) -> None:
    """Print the list of available skills with enabled/disabled status."""
    if not skills:
        _console.print("[dim]No skills available.[/]")
        _console.print(
            "[dim]Add skills as directories with a SKILL.md file under "
            ".mva/skills/ or ~/.mva/skills/[/]"
        )
        return
    table = Table(title="Available Skills", title_style="bold", box=None)
    table.add_column("Status", style="bold", width=10)
    table.add_column("Skill", style="cyan")
    table.add_column("Preview", style="white")
    for s in skills:
        status = "[green]ON[/]" if s.enabled else "[dim]OFF[/]"
        preview = s.content[:80].replace("\n", " ")
        if len(s.content) > 80:
            preview += "…"
        table.add_row(status, s.name, preview)
    _console.print(table)
    _console.print("[dim]Use /skill:<name> to toggle a skill on/off.[/]")


def _toggle_skill(skills: list[SkillDef], name: str) -> None:
    """Toggle a skill's enabled state by name."""
    for s in skills:
        if s.name == name:
            s.enabled = not s.enabled
            status = "enabled" if s.enabled else "disabled"
            _console.print(f"[bold]Skill '{name}' {status}.[/]")
            if s.enabled:
                _console.print(
                    "[dim]Skill content will be included in the next system prompt.[/]"
                )
            return
    _console.print(f"[yellow]Unknown skill:[/] {name}")
    _console.print("Use [bold]/skills[/] to see available skills.")


# ---------------------------------------------------------------------------
# Model / provider commands
# ---------------------------------------------------------------------------


def _print_model_info(client: LLMClient) -> None:
    """Print current provider/model and list all models for this provider."""
    prov = client.current_provider or "(unknown)"
    model = client.default_model or "(no default model)"
    url = client.base_url

    table = Table(title="Current Model", title_style="bold", box=None)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Provider", prov)
    table.add_row("Model", model)
    table.add_row("Base URL", url)
    _console.print(table)

    # Always try to show available models for the current provider
    available = client.available_models
    if available:
        models_table = Table(
            title=f"Models — {prov}", title_style="bold", box=None
        )
        models_table.add_column("Status", style="bold", width=10)
        models_table.add_column("Model", style="cyan")
        for m in available:
            status = "[green]● ACTIVE[/]" if m == model else "[dim]○[/]"
            models_table.add_row(status, m)
        _console.print(models_table)
        _console.print(
            "[dim]Use /model <name> to switch model,"
            " /provider <name> to switch provider.[/]"
        )
    else:
        _console.print(
            "[dim]No models list defined for this provider.[/]"
        )
        _console.print(
            "[dim]Add a 'models:' list to the provider in model.yaml.[/]"
        )


def _switch_model(client: LLMClient, target: str) -> None:
    """Switch to a different model within the current provider.

    ``/model <name>`` — uses the model name directly (must be in the
    current provider's ``available_models`` list, or any model if the
    list is not defined).
    """
    target = target.strip()
    if not target:
        _console.print("[yellow]Usage:[/] /model <model_name>")
        _print_model_info(client)
        return

    if client.set_model(target):
        _console.print(
            f"[green]Model set to '{target}'"
            f" (provider: {client.current_provider}).[/]"
        )
        _print_model_info(client)
    else:
        available = client.available_models
        if available:
            _console.print(
                f"[yellow]Unknown model:[/] '{target}'."
                f" Available: {', '.join(available)}"
            )
        else:
            _console.print(
                f"[yellow]Model '{target}' not found in current"
                f" provider '{client.current_provider}'.[/]"
            )
        _print_model_info(client)


def _switch_provider(client: LLMClient, target: str) -> None:
    """Switch to a different provider from config.

    ``/provider <name>`` — switch provider (and use its default_model).

    Supports ``provider/model`` syntax to also pick a specific model::

        /provider deepseek/deepseek-reasoner
    """
    target = target.strip()
    if not target:
        _console.print(
            "[yellow]Usage:[/] /provider <provider>  or  /provider <provider>/<model>"
        )
        _list_providers(client)
        return

    if "/" in target:
        provider_name, model_name = target.split("/", 1)
        provider_name = provider_name.strip()
        model_name = model_name.strip()
    else:
        provider_name = target
        model_name = None

    if client.switch_provider(provider_name):
        _console.print(
            f"[green]Switched to provider '{provider_name}'.[/]"
        )
        if model_name:
            if client.set_model(model_name):
                _console.print(
                    f"[green]Model set to '{model_name}'.[/]"
                )
            else:
                _console.print(
                    f"[yellow]Model '{model_name}' not found in"
                    f" provider '{provider_name}'.[/]"
                )
        _print_model_info(client)
    else:
        _console.print(
            f"[yellow]Unknown provider:[/] '{provider_name}'."
        )
        _list_providers(client)


def _list_providers(client: LLMClient) -> None:
    """List all available providers from the config file."""
    from mva.config import load_config  # noqa: PLC0415

    try:
        cfg = load_config()
    except Exception:
        _console.print("[dim]No configuration loaded (using env fallback).[/]")
        _console.print(
            "[dim]Set up .mva/model.yaml to define multiple providers.[/]"
        )
        return

    active = cfg.provider
    table = Table(title="Available Providers", title_style="bold", box=None)
    table.add_column("Status", style="bold", width=10)
    table.add_column("Provider", style="cyan")
    table.add_column("Default Model", style="white")
    table.add_column("Models", style="dim")
    table.add_column("Base URL", style="dim")
    for name, p in cfg.providers.items():
        status = "[green]● ACTIVE[/]" if name == active else "[dim]○[/]"
        default_m = p.default_model or "(default)"
        models_str = ", ".join(p.models) if p.models else "—"
        table.add_row(status, name, default_m, models_str, p.base_url)
    _console.print(table)

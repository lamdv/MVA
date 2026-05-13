"""CLI command handlers — display helpers, command dispatch, hot-reload.

Split from ``mva/utils/__init__.py`` during the v2.1 cleanup.  All
functions here depend on ``rich`` and are part of the CLI layer only.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mva_core.agent import get_tool_defs
from mva_core.agent.types import CompletionUsage
from mva_cli.renderer import reset_renderer, stop_spinner

if TYPE_CHECKING:
    from mva_core.agent import Session, SkillDef

_console = Console()


# ---------------------------------------------------------------------------
# Sentinel for commands that need special handling
# ---------------------------------------------------------------------------

_RELOAD_SENTINEL = object()
"""Returned by :func:`handle_command` when the ``/reload`` command is issued.

The REPL loop checks for this sentinel and calls :func:`reload_environment`.
"""

# Module-level plugin manager reference (set by app.py at startup)
_plugin_manager_ref: Any | None = None


def set_plugin_manager(mgr: Any) -> None:
    """Store the active plugin manager for the ``/plugins`` command."""
    global _plugin_manager_ref  # noqa: PLW0603
    _plugin_manager_ref = mgr


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def print_header(*, skills: list[SkillDef] | None = None) -> None:
    """Print the startup header panel."""
    table = Table.grid(padding=0)
    table.add_column(justify="center")
    table.add_row("[bold blue]MVA Chatbot[/]")
    table.add_row("[dim]by lam.dv@live.com[/]")
    # if skills:
    #     loaded = sum(1 for s in skills if s.enabled)
    #     table.add_row(f"[dim]{loaded} of {len(skills)} skill(s) loaded[/]")
    _console.print(Panel(table, border_style="blue", padding=(1, 2)))


def goodbye(*, interrupted: bool = False) -> None:
    """Print a farewell message on exit."""
    print()
    if interrupted:
        _console.print("[dim]Interrupted. Goodbye![/]")
    else:
        _console.print("[dim]Goodbye![/]")


def print_help() -> None:
    """Print the help table listing all available commands."""
    table = Table(title="Commands", title_style="bold", box=None)
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="white")
    table.add_row("/exit, /quit", "Exit the chatbot")
    table.add_row("/clear, /reset", "Clear conversation history")
    table.add_row("/help", "Show this help message")
    table.add_row("/history", "Show recent conversation history")
    table.add_row("/model", "Show current model and list available models")
    table.add_row("/model <name>", "Switch model (accepts provider/model syntax)")
    table.add_row("/provider, /providers", "List available providers")
    table.add_row("/provider <name>", "Switch to a different provider")
    table.add_row("/tools", "List available tools")
    table.add_row("/skills", "List available skills")
    table.add_row("/skill:<name>", "Enable/disable a skill")
    table.add_row("/plugins", "List loaded REPL plugins")
    table.add_row("/save", "Save session (auto-generated ID)")
    table.add_row("/save <name>", "Save session with a friendly name")
    table.add_row("/load <id>", "Load a saved session")
    table.add_row("/sessions, /saves", "List saved sessions")
    table.add_row("/delete <id>", "Delete a saved session")
    table.add_row("/export", "Export conversation as Markdown (stdout)")
    table.add_row("/export <file>", "Export conversation to a file")
    table.add_row("/reload", "Hot-reload tools and skills (re-scan directories)")
    table.add_row("/usage", "Show cumulative token usage for this session")
    _console.print(table)


# ---------------------------------------------------------------------------
# Conversation export
# ---------------------------------------------------------------------------


def _export_history(
    history: list[dict[str, Any]],
    session: Session,
    path: str = "",
) -> None:
    """Export conversation history as Markdown to *stdout* or a *path*."""
    if not history:
        if path:
            _console.print("[yellow]No conversation to export.[/]")
        else:
            print("*No conversation yet.*")
        return

    lines: list[str] = []

    # --- Header ---
    lines.append("# MVA Conversation\n")
    lines.append(f"*Exported: {datetime.now(timezone.utc).isoformat()}*\n")
    prov = session.current_provider or "?"
    model = session.client.default_model or "?"
    lines.append(f"*Provider: {prov} / {model}*\n")
    user_turns = sum(1 for m in history if m["role"] == "user")
    lines.append(f"*Turns: {user_turns}*\n")
    usage = session.total_usage
    if usage and usage.total_tokens > 0:
        lines.append(
            f"*Tokens: {usage.total_tokens}∑  "
            f"({usage.prompt_tokens}↑ {usage.completion_tokens}↓)*\n"
        )
    lines.append("---\n")

    # --- History turns ---
    for turn in history:
        role = turn["role"]

        if role == "user":
            content = turn.get("content", "")
            lines.append(f"\n## 🧑 User\n\n{content}\n")

        elif role == "assistant":
            content = turn.get("content", "")
            reasoning = turn.get("reasoning_content")
            tool_calls = turn.get("tool_calls")

            if tool_calls:
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    args = tc["function"]["arguments"]
                    lines.append(f"\n## 🔧 Tool Call: {name}\n\n```json\n{args}\n```\n")
            elif content:
                if reasoning:
                    lines.append(
                        f"\n<details>\n<summary>💭 Reasoning</summary>\n\n"
                        f"{reasoning}\n\n</details>\n"
                    )
                lines.append(f"\n## 🤖 Assistant\n\n{content}\n")

        elif role == "tool":
            content = turn.get("content", "")
            preview = content[:500]
            if len(content) > 500:
                preview += "\n\n… *(truncated)*"
            lines.append(f"\n## 📄 Tool Result\n\n```\n{preview}\n```\n")

    output = "".join(lines)

    if path:
        Path(path).write_text(output)
        _console.print(f"[green]Exported to {path}[/]")
    else:
        print(output, end="")


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

_SESSION_DIR = Path.home() / ".config" / "mva" / "sessions"


def _generate_session_id() -> str:
    """Generate a short random session ID (8 hex chars)."""
    return secrets.token_hex(4)


def _save_session(
    history: list[dict[str, Any]],
    session: Session,
    name: str = "",
) -> str:
    """Save conversation history and export as Markdown.

    Returns the session ID (or the friendly name used).
    When *name* is empty, an 8-char hex ID is auto-generated.
    """
    sid = name.strip() or _generate_session_id()
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # --- JSON (for machine loading) ---
    json_path = _SESSION_DIR / f"{sid}.json"
    data = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "provider": session.current_provider,
        "model": session.client.default_model,
        "usage": {
            "prompt_tokens": session.total_usage.prompt_tokens,
            "completion_tokens": session.total_usage.completion_tokens,
            "total_tokens": session.total_usage.total_tokens,
        },
        "history": history,
    }
    json_path.write_text(json.dumps(data, indent=2))

    n_turns = len([m for m in history if m["role"] == "user"])
    _console.print(
        f"[green]Session saved as '{sid}' ({n_turns} turn(s), "
        f"{len(history)} message(s)).[/]"
    )
    return sid


def _load_session(session: Session, sid: str) -> bool:
    """Restore conversation history from a saved session.

    Returns ``True`` on success, ``False`` if not found.
    Optionally restores provider and model from the saved session.
    """
    json_path = _SESSION_DIR / f"{sid}.json"
    if not json_path.exists():
        _console.print(f"[yellow]No saved session '{sid}'.[/]")
        return False

    data = json.loads(json_path.read_text())

    # Restore history
    session.history.clear()
    session.history.extend(data["history"])

    # Restore provider/model if available
    if data.get("provider"):
        session.switch_provider(data["provider"])
    if data.get("model"):
        session.set_model(data["model"])

    # Restore usage
    usage = data.get("usage")
    if usage:
        from mva_core.agent.types import CompletionUsage
        session.total_usage = CompletionUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )

    _console.print(
        f"[green]Session '{sid}' loaded ({len(data['history'])} messages).[/]"
    )
    return True


def _list_sessions() -> None:
    """List all saved sessions."""
    if not _SESSION_DIR.exists():
        _console.print("[dim]No saved sessions.[/]")
        return

    json_files = sorted(_SESSION_DIR.glob("*.json"))
    if not json_files:
        _console.print("[dim]No saved sessions.[/]")
        return

    table = Table(title="Saved Sessions", title_style="bold", box=None)
    table.add_column("ID", style="cyan")
    table.add_column("Saved At", style="white")
    table.add_column("Turns", style="dim")
    table.add_column("Messages", style="dim")
    table.add_column("Provider", style="dim")
    table.add_column("Model", style="dim")

    for jf in json_files:
        try:
            data = json.loads(jf.read_text())
            sid = jf.stem
            saved = data.get("saved_at", "?")[:19].replace("T", " ")
            turns = sum(1 for m in data["history"] if m["role"] == "user")
            msgs = len(data["history"])
            prov = data.get("provider", "?")
            model = data.get("model", "?")
            table.add_row(sid, saved, str(turns), str(msgs), prov, model)
        except Exception:
            table.add_row(jf.stem, "[red]corrupt[/]", "", "", "", "")

    _console.print(table)
    _console.print("[dim]Use /load <id> to restore, /delete <id> to remove.[/]")


def _delete_session(sid: str) -> None:
    """Delete a saved session."""
    p = _SESSION_DIR / f"{sid}.json"
    if p.exists():
        p.unlink()
        _console.print(f"[green]Deleted session '{sid}'.[/]")
    else:
        _console.print(f"[yellow]No saved session '{sid}'.[/]")


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------


def handle_command(
    raw: str,
    history: list[dict[str, Any]],
    session: Session,
    *,
    skills: list[SkillDef] | None = None,
) -> bool | None:
    """Dispatch a ``/command`` entered by the user.

    Returns ``False`` to signal exit, ``_RELOAD_SENTINEL`` to signal
    reload, or ``True`` for normal completion.
    """
    cmd = raw[1:].strip()

    if cmd in ("exit", "quit", "q"):
        goodbye()
        return False

    if cmd in ("clear", "cls", "reset"):
        # Clear the conversation history via the Session's dedicated method
        session.clear()
        # Reset accumulated token usage
        session.total_usage = CompletionUsage()
        # Stop any active spinner from a previous incomplete stream
        stop_spinner()
        # Reset the renderer's per-turn state (buffers, phase tracking)
        reset_renderer()
        # Clear the terminal screen AND scrollback buffer
        _console.clear()
        _console.print("\033[3J", end="")  # clear scrollback (vt100)
        print_header()
        _console.print("[dim]Conversation cleared.[/]")
        return True

    if cmd == "help":
        print_help()
        return True

    if cmd == "model":
        _print_model_info(session)
        return True

    if cmd.startswith("model "):
        _switch_model(session, cmd[6:].strip())
        return True

    if cmd in ("provider", "providers"):
        _list_providers(session)
        return True

    if cmd.startswith("provider "):
        # if cmd.startswith("provider add "):
        #     _add_provider(session, cmd.split(" ")[-1])
        #     return True
        # if cmd.startswith("provider rm "):
        #     _rm_provider(session, cmd.split(" ")[-1])
        _switch_provider(session, cmd[9:].strip())
        return True

    if cmd == "reload":
        return _RELOAD_SENTINEL

    if cmd == "tools":
        _print_tools()
        return True

    if cmd == "skills":
        _print_skills(skills or [])
        return True

    if cmd == "plugins":
        _print_plugins()
        return True

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

    if cmd == "usage":
        _print_usage(session)
        return True

    if cmd in ("ping", "test"):
        _console.print(
            f"[dim]Testing connection to {session.current_provider or '?'} / "
            f"{session.client.default_model or '?'} ...[/]"
        )
        ok, err = session.test_connection()
        if ok:
            _console.print("[green]✓ Connection OK[/]")
        else:
            _console.print(f"[red]✗ Connection failed: {err}[/]")
        return True

    if cmd == "export":
        _export_history(history, session)
        return True

    if cmd.startswith("export "):
        filepath = cmd[7:].strip()
        if not filepath:
            _console.print("[yellow]Usage: /export <filepath>[/]")
            return True
        _export_history(history, session, path=filepath)
        return True

    if cmd == "save":
        _save_session(history, session)
        return True

    if cmd.startswith("save "):
        _save_session(history, session, name=cmd[5:].strip())
        return True

    if cmd.startswith("load "):
        sid = cmd[5:].strip()
        if not sid:
            _console.print("[yellow]Usage: /load <id>[/]")
            return True
        _load_session(session, sid)
        return True

    if cmd in ("sessions", "saves"):
        _list_sessions()
        return True

    if cmd.startswith("delete "):
        sid = cmd[7:].strip()
        if not sid:
            _console.print("[yellow]Usage: /delete <id>[/]")
            return True
        _delete_session(sid)
        return True

    _console.print(f"[yellow]Unknown command:[/] {raw}")
    _console.print("Type [bold]/help[/] for available commands.")
    return True


# ---------------------------------------------------------------------------
# Tool / skill display
# ---------------------------------------------------------------------------


def _print_plugins() -> None:
    """Print the list of loaded plugins."""
    if _plugin_manager_ref is None:
        _console.print("[dim]No plugin manager loaded.[/]")
        return
    plugins = _plugin_manager_ref.plugins
    if not plugins:
        _console.print("[dim]No plugins loaded.[/]")
        _console.print(
            "[dim]Add plugins as Python files under "
            ".mva/plugins/ or install packages with "
            "mva.repl_plugins entry points.[/]"
        )
        return
    table = Table(title="Loaded Plugins", title_style="bold", box=None)
    table.add_column("Plugin", style="cyan")
    table.add_column("Description", style="white")
    for p in plugins:
        table.add_row(p.name, p.description)
    _console.print(table)


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


def _print_model_info(session: Session) -> None:
    """Print current provider/model and list all models for this provider."""
    prov = session.current_provider or "(unknown)"
    model = session.client.default_model or "(no default model)"
    url = session.client.base_url

    table = Table(title="Current Model", title_style="bold", box=None)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Provider", prov)
    table.add_row("Model", model)
    table.add_row("Base URL", url)
    _console.print(table)

    available = session.available_models
    if available:
        models_table = Table(title=f"Models — {prov}", title_style="bold", box=None)
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
        _console.print("[dim]No models list defined for this provider.[/]")
        _console.print("[dim]Add a 'models:' list to the provider in model.yaml.[/]")


def _switch_model(session: Session, target: str) -> None:
    """Switch to a different model.

    ``/model <name>`` — uses the model name directly.
    ``/model <provider>/<model>`` — switch provider and model in one command.
    """
    target = target.strip()
    if not target:
        _console.print(
            "[yellow]Usage:[/] /model <model_name>  or  /model <provider>/<model>"
        )
        _print_model_info(session)
        return

    if "/" in target:
        provider_name, model_name = target.split("/", 1)
        provider_name = provider_name.strip()
        model_name = model_name.strip()

        if not provider_name or not model_name:
            _console.print(
                "[yellow]Usage:[/] /model <provider>/<model>"
                " — both parts are required.[/]"
            )
            return

        if session.switch_provider(provider_name):
            _console.print(f"[green]Switched to provider '{provider_name}'.[/]")
            if session.set_model(model_name):
                _console.print(f"[green]Model set to '{model_name}'.[/]")
            else:
                available = session.available_models
                if available:
                    _console.print(
                        f"[yellow]Model '{model_name}' not in"
                        f" provider '{provider_name}'."
                        f" Available: {', '.join(available)}[/]"
                    )
                else:
                    _console.print(
                        f"[yellow]Model '{model_name}' not found in"
                        f" provider '{provider_name}'.[/]"
                    )
            _print_model_info(session)
            # Connection test
            ok, err = session.test_connection()
            if ok:
                _console.print("[green]✓ Connection OK[/]")
            else:
                _console.print(f"[red]✗ Connection failed: {err}[/]")
        else:
            _console.print(f"[yellow]Unknown provider:[/] '{provider_name}'.")
            _list_providers(session)
        return

    if session.set_model(target):
        status = (
            f"[green]Model set to '{target}'"
            f" (provider: {session.current_provider}).[/]"
        )
        if not session.available_models:
            status += (
                "\n[yellow]Warning:[/] No models list defined for this provider. "
                "The model may not exist on the server."
            )
        _console.print(status)
        _print_model_info(session)
    else:
        available = session.available_models
        if available:
            _console.print(
                f"[yellow]Unknown model:[/] '{target}'."
                f" Available: {', '.join(available)}"
            )
        else:
            _console.print(
                f"[yellow]Model '{target}' not found in current"
                f" provider '{session.current_provider}'.[/]"
            )
        _print_model_info(session)


def _add_provider(
    session: Session,
):
    """Add a new provider

    ``/provider add <name>``
    """
    pass


def _rm_provider(session: Session, name: str) -> None:
    """Remove a provider from config"""
    pass


def _switch_provider(session: Session, target: str) -> None:
    """Switch to a different provider from config.

    ``/provider <name>`` — switch provider.
    ``/provider <provider>/<model>`` — switch provider and model.
    """
    target = target.strip()
    if not target:
        _console.print(
            "[yellow]Usage:[/] /provider <provider>  or  /provider <provider>/<model>"
        )
        _list_providers(session)
        return

    if "/" in target:
        provider_name, model_name = target.split("/", 1)
        provider_name = provider_name.strip()
        model_name = model_name.strip()
    else:
        provider_name = target
        model_name = None

    if session.switch_provider(provider_name):
        _console.print(f"[green]Switched to provider '{provider_name}'.[/]")
        if model_name:
            if session.set_model(model_name):
                _console.print(f"[green]Model set to '{model_name}'.[/]")
            else:
                _console.print(
                    f"[yellow]Model '{model_name}' not found in"
                    f" provider '{provider_name}'.[/]"
                )
        _print_model_info(session)
        # Connection test
        ok, err = session.test_connection()
        if ok:
            _console.print("[green]✓ Connection OK[/]")
        else:
            _console.print(f"[red]✗ Connection failed: {err}[/]")
    else:
        _console.print(f"[yellow]Unknown provider:[/] '{provider_name}'.")
        _list_providers(session)


def _list_providers(session: Session) -> None:
    """List all available providers from the config file."""
    from mva_core.config import load_config  # noqa: PLC0415

    try:
        cfg = load_config()
    except Exception:
        _console.print("[dim]No configuration loaded (using env fallback).[/]")
        _console.print("[dim]Set up .mva/model.yaml to define multiple providers.[/]")
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


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------


def _print_usage(session: Session) -> None:
    """Print cumulative token usage for the current session."""
    usage = session.total_usage
    if usage.total_tokens == 0:
        _console.print("[dim]No token usage data yet.[/]")
        return

    table = Table(title="Token Usage (Session)", title_style="bold", box=None)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="white")
    table.add_row("Prompt tokens", str(usage.prompt_tokens))
    table.add_row("Completion tokens", str(usage.completion_tokens))
    table.add_row("Total tokens", str(usage.total_tokens))
    _console.print(table)


# ---------------------------------------------------------------------------
# Hot reload
# ---------------------------------------------------------------------------


def reload_environment(
    agent_session: Any,
    skills: list[Any],
) -> list[Any]:
    """Hot-reload tools and skills in-place.

    Called by the REPL loop when the user types ``/reload``.

    1. Clears the tool registry and re-discovers everything.
    2. Updates ``agent_session.tools`` with fresh tool definitions.
    3. Re-discovers skills and replaces the *skills* list in-place
       (preserving enable/disable state by name).
    """
    from mva_core.tools.builtin import register_all  # noqa: PLC0415
    from mva_core.tools.registry import get_default_registry  # noqa: PLC0415
    from mva_core.skills import discover_skills  # noqa: PLC0415

    registry = get_default_registry()
    registry.reload_all(builtins_fn=register_all)

    agent_session.tools = get_tool_defs()

    old_state = {s.name: s.enabled for s in skills}
    new_skills = discover_skills()

    for s in new_skills:
        if s.name in old_state:
            s.enabled = old_state[s.name]

    skills.clear()
    skills.extend(new_skills)

    _console.print("[green]✓ Tools and skills reloaded.[/]")
    _print_tools()
    _print_skills(skills)

    return skills

"""MVA CLI application — Typer entry point.

Creates an :class:`~mva.agent.Session` (the agent) and hands it to
the REPL loop or single-run handler.
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console

from mva.cli.console import _create_prompt_session, set_session, set_skills
from mva.cli.repl import _repl, _run_single
from mva.agent import Session, discover_skills, get_tool_defs
from mva.utils import (
    build_system_prompt,
    install_signal_handler,
    print_header,
)

_console = Console()

_app = typer.Typer(
    name="mva",
    help="MVA — Minimum Viable Agent harness.",
    add_completion=False,
)


@_app.command()
def app(
    message: list[str] | None = typer.Argument(
        None, help="Task to run (non-interactive when provided)."
    ),
    print_mode: bool = typer.Option(
        False,
        "--print",
        "-p",
        help="Print response and exit (non-interactive).",
    ),
    system_prompt: str | None = typer.Option(
        None, "--system-prompt", help="Replace the default system prompt."
    ),
    append_system_prompt: str | None = typer.Option(
        None, "--append-system-prompt", help="Append text to the system prompt."
    ),
    skill: list[str] | None = typer.Option(
        None,
        "--skill",
        "-s",
        help="Load a skill from a directory or SKILL.md file (repeatable).",
    ),
    no_skills: bool = typer.Option(
        False, "--no-skills", help="Disable all skill loading."
    ),
    no_context_files: bool = typer.Option(
        False,
        "--no-context-files",
        "-nc",
        help="Disable AGENT.md context file loading.",
    ),
) -> None:
    """Launch the MVA interactive REPL, or run a single task non-interactively."""
    install_signal_handler()

    # Discover skills at startup
    skills = discover_skills(
        extra_dirs=skill,
        no_skills=no_skills,
    )
    set_skills(skills)

    # Build the user message: CLI argument(s) + optional piped stdin
    user_message = " ".join(message) if message else ""
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            user_message = f"{piped}\n\n{user_message}" if user_message else piped
    user_message = user_message.strip()

    session: Session | None = None
    agent_md_path: str | None = None if no_context_files else "AGENT.md"

    try:
        if print_mode or message:
            # Non-interactive single-run mode
            _run_single(
                user_message,
                skills,
                system_prompt=system_prompt,
                append_system_prompt=append_system_prompt,
                agent_md_path=agent_md_path,
            )
        else:
            # Interactive REPL
            print_header(skills=skills if skills else None)

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
                on_confirm=None,  # set by _repl when needed
            )
            set_session(session)

            pt_session = _create_prompt_session()
            _repl(
                pt_session,
                session,
                skills,
                system_prompt=system_prompt,
                append_system_prompt=append_system_prompt,
                agent_md_path=agent_md_path,
            )
    finally:
        if session is not None:
            session.client.close()

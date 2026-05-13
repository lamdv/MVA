"""Core system utilities — signal handling, system prompt building, message construction.

This module is part of the **agent** package (not CLI) so that non-CLI
consumers (web UI, GUI, scripts) can import it without pulling in
``rich``, ``typer``, or ``prompt-toolkit``.

Split from ``mva/utils/__init__.py`` during the v2.1 cleanup.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mva_core.agent.types import ChatMessage, ToolDef, SkillDef


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert coding assistant operating inside MVA, a coding agent "
    "harness. You help users by reading files, executing commands, editing "
    "code, and writing new files."
)


# ---------------------------------------------------------------------------
# Stream cancellation support
# ---------------------------------------------------------------------------

_streaming_active = False
_cancel_requested = False
_cancel_first_press: float = 0.0
"""Timestamp of the first Ctrl+C during streaming (for debounce)."""

_DEBOUNCE_SECONDS = 2.0
"""If a second Ctrl+C arrives within this window, do a hard exit."""


def _mark_streaming_start() -> None:
    """Mark that a streaming response is in progress (called from CLI)."""
    global _streaming_active, _cancel_requested, _cancel_first_press
    _streaming_active = True
    _cancel_requested = False
    _cancel_first_press = 0.0


def _mark_streaming_stop() -> None:
    """Mark that streaming has ended."""
    global _streaming_active
    _streaming_active = False


def is_cancel_requested() -> bool:
    """Check whether the user has requested cancellation of the current stream."""
    return _cancel_requested


def install_signal_handler() -> None:
    """Install the SIGINT handler for graceful cancellation.

    First Ctrl+C during streaming → cancels the current request and
    prints feedback.  A second Ctrl+C within 2 seconds → hard exit.
    At the prompt, Ctrl+C is handled by prompt-toolkit's key binding.
    """
    signal.signal(signal.SIGINT, _signal_handler)


def _signal_handler(signum: int, _frame: Any) -> None:
    global _cancel_requested, _cancel_first_press

    if not _streaming_active:
        return  # prompt-toolkit handles it

    now = time.monotonic()

    # Second Ctrl+C within debounce window → hard exit
    if _cancel_requested and _cancel_first_press > 0:
        if now - _cancel_first_press < _DEBOUNCE_SECONDS:
            sys.stderr.write("\n(Hard exit)\n")
            sys.stderr.flush()
            signal.signal(signal.SIGINT, signal.SIG_DFL)  # restore default
            sys.exit(1)

    # First Ctrl+C → cancel gracefully
    if not _cancel_requested:
        _cancel_first_press = now
        _cancel_requested = True
        sys.stderr.write("\n⏳ Cancelling… (Ctrl+C again to force)\n")
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# System prompt (tool-aware)
# ---------------------------------------------------------------------------


def _tool_snippet(t: ToolDef) -> str:
    """Extract a one-line snippet from a tool definition."""
    desc = t.description
    for cut in (". ", ".\n", ".  "):
        idx = desc.find(cut)
        if idx != -1:
            desc = desc[: idx + 1]
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
    """
    from mva_core.skills import build_skills_prompt  # noqa: PLC0415

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
    """Build a message list suitable for the chat completions API."""
    from mva_core.agent.types import ChatMessage  # noqa: PLC0415

    messages: list[ChatMessage] = []

    if system:
        messages.append(ChatMessage(role="system", content=system))

    for turn in history:
        role = turn["role"]
        content = turn.get("content", "")

        if role == "tool":
            messages.append(
                ChatMessage(
                    role="tool",
                    content=str(content),
                    tool_call_id=turn.get("tool_call_id", ""),
                )
            )
        elif role == "assistant" and turn.get("tool_calls"):
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=content or "",
                    tool_calls=turn["tool_calls"],
                    reasoning_content=turn.get("reasoning_content"),
                )
            )
        elif role == "assistant":
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=content,
                    reasoning_content=turn.get("reasoning_content"),
                )
            )
        else:
            messages.append(ChatMessage(role=role, content=content))

    messages.append(ChatMessage(role="user", content=new_user_msg))
    return messages

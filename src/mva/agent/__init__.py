"""Agent submodule.

Provides an ``Agent`` class with optional tool-calling and skill discovery capabilities,
all built on the same ``LlamaClient`` transport layer:

- ``Agent``         — core class: system prompt injection, tool calling, skill discovery
- ``Tool``          — wraps callables with metadata for LLM function calling
- ``SkillCatalog``  — manages skill discovery from SKILL.md files
- ``get_agent``     — convenience factory with auto-discovery from config
"""

from pathlib import Path

from .base import Agent
from .tools import Tool, ToolsNotSupportedError, sandbox
from .skills import SkillCatalog


def _resolve_tools_dir(override: str | None = None) -> Path | None:
    """Return the tools directory to watch, or ``None`` if none is configured.

    Resolution order:
    1. *override* argument
    2. ``tools_dir`` key in config.yml
    3. ``./tools/`` (local)
    4. ``~/.config/private-notebook/tools/``
    """
    if override is None:
        from ..utils.config import load_config
        override = load_config().get("tools_dir")

    if override is not None:
        path = Path(override).expanduser()
        return path if path.is_dir() else None

    for candidate in (
        Path("tools"),
        Path.home() / ".config" / "private-notebook" / "tools",
    ):
        if candidate.is_dir():
            return candidate

    return None


def _resolve_skills_dir(override: str | None = None) -> Path | None:
    """Return the skills directory to watch, or ``None`` if none is configured.

    Resolution order:
    1. *override* argument
    2. ``skills_dir`` key in config.yml
    3. ``./kb/skills/`` (local)
    4. ``~/.config/private-notebook/skills/``
    """
    if override is None:
        from ..utils.config import load_config
        override = load_config().get("skills_dir")

    if override is not None:
        path = Path(override).expanduser()
        return path if path.is_dir() else None

    for candidate in (
        Path("kb/skills"),
        Path.home() / ".config" / "private-notebook" / "skills",
    ):
        if candidate.is_dir():
            return candidate

    return None


def _load_soul(cfg: dict) -> str | None:
    """Load SOUL.md content from path configured in config.yml (soul_file key).

    Returns the file content as a string, or None if not configured / not found.
    """
    soul_path_str = cfg.get("soul_file")
    if not soul_path_str:
        return None
    soul_path = Path(soul_path_str).expanduser()
    if not soul_path.exists():
        return None
    return soul_path.read_text(encoding="utf-8").strip() or None


def get_agent(*, skills_dir: str | None = None, **kwargs) -> Agent:
    """Convenience factory returning an ``Agent`` with auto-discovered tools and skills.

    Args:
        skills_dir: Optional override for the skills directory path.
        **kwargs: Additional arguments passed to Agent (system_prompt, model, temperature, etc.)
    """
    from ..utils.config import load_config

    cfg = load_config()

    soul = _load_soul(cfg)
    if soul:
        existing = kwargs.get("system_prompt") or ""
        kwargs["system_prompt"] = (soul + "\n\n" + existing).strip() if existing else soul

    tools_dir = _resolve_tools_dir()
    resolved_skills = _resolve_skills_dir(skills_dir)

    # Self-improvement: pass telemetry_dir and reflection config if configured
    # NOTE: Generated tools are NOT auto-loaded. User must explicitly promote them via CLI.
    si_cfg = cfg.get("self_improvement", {})
    if si_cfg:
        telemetry_dir = si_cfg.get("telemetry_dir")
        if telemetry_dir:
            kwargs["telemetry_dir"] = Path(telemetry_dir).expanduser()

            # Pass reflection triggers (Phase 2)
            reflection_config = {
                "reflect_always": si_cfg.get("reflect_always", False),
                "fail_rate_threshold": si_cfg.get("fail_rate_threshold"),
                "slow_tool_threshold_ms": si_cfg.get("slow_tool_threshold_ms"),
            }
            kwargs["reflection_config"] = reflection_config

    return Agent(tools_dir=tools_dir, skills_dir=resolved_skills, **kwargs)


__all__ = ["Agent", "Tool", "ToolsNotSupportedError", "SkillCatalog", "get_agent", "sandbox"]

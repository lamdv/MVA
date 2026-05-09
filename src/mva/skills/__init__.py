"""Skill discovery and loading for MVA.

Skills are on-demand capability packages following the `Agent Skills
standard <https://agentskills.io>`_.  Each skill lives in a directory
containing a ``SKILL.md`` file with instructions the model can follow.

Skills are discovered from:

* ``.mva/skills/`` — walking **up** from the current working directory
  through parent directories (project-level)
* ``~/.mva/skills/`` — global, user-level skills

Use ``MVA_NO_SKILLS=1`` to disable skill loading entirely.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class SkillDef:
    """Metadata and content of a single skill."""

    name: str
    """Directory name of the skill (used as the skill identifier)."""

    path: Path
    """Absolute path to the skill directory."""

    content: str
    """Contents of the ``SKILL.md`` file."""

    enabled: bool = True
    """Whether the skill is currently active (injected into the system prompt)."""


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _walk_up_for_skills(start: Path) -> list[Path]:
    """Walk from *start* up through parents collecting ``.mva/skills/`` dirs.

    Returns a list ordered from the most distant ancestor to *start* itself
    (closest last), so that closer skills can override names if needed.
    """
    candidates: list[Path] = []
    current = start.resolve()
    root = current.anchor  # "/" on Unix, "C:\\" on Windows

    while True:
        skills_dir = current / ".mva" / "skills"
        if skills_dir.is_dir():
            candidates.append(skills_dir)
        if current == Path(root):
            break
        current = current.parent

    candidates.reverse()  # closest (CWD) last
    return candidates


def _home_skills_dir() -> Path | None:
    """Return ``~/.mva/skills/`` if it exists, otherwise ``None``."""
    home = Path.home() / ".mva" / "skills"
    return home if home.is_dir() else None


def _read_skill_dir(skills_dir: Path) -> list[SkillDef]:
    """Scan a skills directory for subdirectories containing ``SKILL.md``."""
    result: list[SkillDef] = []
    if not skills_dir.is_dir():
        return result

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if not content:
            continue

        result.append(
            SkillDef(
                name=entry.name,
                path=entry.resolve(),
                content=content,
            )
        )

    return result


def discover_skills(
    *,
    extra_dirs: list[str] | None = None,
    no_skills: bool = False,
) -> list[SkillDef]:
    """Discover all available skills and return them as :class:`SkillDef` objects.

    Parameters
    ----------
    extra_dirs:
        Additional directories to scan for skills (resolved as-is, no
        parent-walking).
    no_skills:
        When ``True``, return an empty list (used to disable all skills).

    Returns
    -------
    A list of skills, de-duplicated by name (closest definition wins).
    """
    if no_skills:
        return []

    # Check env-var override
    if os.environ.get("MVA_NO_SKILLS", "").strip() in ("1", "true", "yes"):
        return []

    seen: dict[str, SkillDef] = {}

    # 1. Global skills (~/.mva/skills/) — loaded first, overridable
    home_dir = _home_skills_dir()
    if home_dir is not None:
        for skill in _read_skill_dir(home_dir):
            seen[skill.name] = skill

    # 2. Project skills walking up from CWD — closest wins on name conflict
    for skills_dir in _walk_up_for_skills(Path.cwd()):
        for skill in _read_skill_dir(skills_dir):
            seen[skill.name] = skill

    # 3. Extra directories (from --skill flags or env)
    if extra_dirs:
        for dirpath in extra_dirs:
            path = Path(dirpath).expanduser().resolve()
            if path.is_dir():
                for skill in _read_skill_dir(path):
                    seen[skill.name] = skill

    return list(seen.values())


# ---------------------------------------------------------------------------
# System prompt injection
# ---------------------------------------------------------------------------


def build_skills_prompt(skills: list[SkillDef]) -> str:
    """Build the skills section of the system prompt.

    Only includes skills that are currently enabled.
    Uses a reference format: the model is told to read the skill file
    rather than having the full content inlined.
    Returns an empty string if no skills are enabled.
    """
    active = [s for s in skills if s.enabled]
    if not active:
        return ""

    lines: list[str] = [
        "",
        "The following skills provide specialized instructions for specific tasks.",
        "Use the read tool to load a skill's SKILL.md when the task matches.",
        "",
        "<available_skills>",
    ]

    for skill in active:
        skill_md = skill.path / "SKILL.md"
        lines.append("  <skill>")
        lines.append(f"    <name>{skill.name}</name>")
        lines.append(f"    <location>{skill_md}</location>")
        # First line of content as brief description
        first_line = skill.content.split("\n")[0].lstrip("#").strip()
        lines.append(f"    <description>{first_line}</description>")
        lines.append("  </skill>")

    lines.append("</available_skills>")
    return "\n".join(lines)

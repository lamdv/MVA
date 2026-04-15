"""Skill discovery and management for the Agent."""
from __future__ import annotations

from pathlib import Path


def _parse_skill_metadata(skill_md: Path) -> dict | None:
    """Parse YAML frontmatter from a SKILL.md file.

    Returns a dict with 'name' and 'description' keys, or None if invalid.
    """
    try:
        import yaml
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        end = text.find("---", 3)
        if end == -1:
            return None
        front = yaml.safe_load(text[3:end])
        if not isinstance(front, dict):
            return None
        name = front.get("name", "")
        description = front.get("description", "")
        if not name or not description:
            return None
        return {"name": name, "description": description}
    except Exception:
        return None


class SkillCatalog:
    """Manages skill discovery and registration."""

    def __init__(self, skills_dir: Path | str | None = None):
        self._skills_dir: Path | None = Path(skills_dir) if skills_dir else None
        self._skill_mtimes: dict[Path, float] = {}
        self._skill_catalog: dict[str, dict] = {}  # name -> {description, path}

    def refresh(self) -> None:
        """Re-scan skills directory; reload changed SKILL.md files."""
        if self._skills_dir is None or not self._skills_dir.is_dir():
            return

        seen = set()
        for skill_md in self._skills_dir.rglob("SKILL.md"):
            try:
                mtime = skill_md.stat().st_mtime
            except OSError:
                continue
            seen.add(skill_md)
            if self._skill_mtimes.get(skill_md) == mtime:
                continue  # unchanged
            self._skill_mtimes[skill_md] = mtime
            meta = _parse_skill_metadata(skill_md)
            if meta:
                self._skill_catalog[meta["name"]] = {
                    "description": meta["description"],
                    "path": skill_md,
                }

        # Remove deleted skills
        for removed in set(self._skill_mtimes) - seen:
            del self._skill_mtimes[removed]
        self._skill_catalog = {
            name: info for name, info in self._skill_catalog.items()
            if info["path"] in seen
        }

    @property
    def catalog(self) -> dict[str, dict]:
        """Return the skill catalog."""
        return self._skill_catalog

    def load_skill(self, name: str) -> str:
        """Load full instructions for a skill by name."""
        info = self._skill_catalog.get(name)
        if not info:
            available = ", ".join(sorted(self._skill_catalog.keys()))
            return f"Skill '{name}' not found. Available: {available}"
        return info["path"].read_text(encoding="utf-8")

    def system_prompt_injection(self, base_prompt: str | None = None) -> str:
        """Generate system prompt injection with skill catalog."""
        if not self._skill_catalog:
            return base_prompt or ""

        catalog_lines = [
            "## Available Skills\n",
            "Skills are high-level workflows that guide you through complex tasks.",
            "They are distinct from tools (lower-level functions).\n"
        ]
        for name, info in sorted(self._skill_catalog.items()):
            catalog_lines.append(f"- **{name}**: {info['description']}")
        catalog_lines.append("\n**How to use skills:**")
        catalog_lines.append("1. Call `load_skill(name)` to read the full skill instructions")
        catalog_lines.append("2. Follow the step-by-step workflow described in the skill")
        catalog_lines.append("3. Use the tools it recommends to complete the task")
        catalog_lines.append("\n**Note:** Do NOT confuse skills with the tools you can directly call.")
        catalog_block = "\n".join(catalog_lines)

        if base_prompt:
            return (base_prompt + "\n\n" + catalog_block).strip()
        return catalog_block

"""mva-core — Agent logic, tools, skills, and configuration.

This package has **zero** UI dependencies (no rich, typer, or
prompt-toolkit).  It can be used standalone by non-CLI consumers
such as web UIs, GUIs, or scripts.
"""

from __future__ import annotations

from mva_core.agent import (
    LLMClient,
    Session,
    SkillDef,
    ToolResult,
    build_skills_prompt,
    discover_skills,
    execute_tool,
    get_tool_defs,
)
from mva_core.tools import Tool, ToolDef, ToolRegistry, ToolResult as ToolResult_

# Re-export commonly used types
__all__ = [
    "LLMClient",
    "Session",
    "SkillDef",
    "Tool",
    "ToolDef",
    "ToolRegistry",
    "ToolResult",
    "build_skills_prompt",
    "discover_skills",
    "execute_tool",
    "get_tool_defs",
]

"""Tool definitions, executors, and registry for the MVA chatbot.

Tools follow the OpenAI function calling convention.  There are two
styles for defining tools:

**Class-based** (for built-in / complex tools) — subclass
:class:`~mva.tools.base.Tool`:

    class MyTool(Tool):
        name = "my_tool"
        description = "Does something."
        parameters = {"type": "object", "properties": {...}}
        prompt_snippet = "Short one-liner"  # optional

        def execute(self, **kwargs) -> ToolResult: ...
        def check_security(self, **kwargs) -> SecurityCheck | None: ...

**Imperative** (for external / simple tools) — module-level
convention.  Drop a ``.py`` file in ``.mva/tools/``::

    # .mva/tools/my_tool.py
    name = "my_tool"
    description = "Does something."
    parameters = {"type": "object", "properties": {...}}

    def execute(**kwargs):
        return "result"  # or ToolResult, or dict

    # Optional security check
    def check_security(**kwargs):
        return None  # or {"safe": False, "message": "..."}

External tools are auto-discovered from ``.mva/tools/`` (walking up
from CWD), ``~/.mva/tools/``, and pip packages via the ``mva.tools``
entry-point group.

For backward compatibility, the :func:`get_tool_defs` and
:func:`execute_tool` functions still work against the module-level
default registry.
"""

from __future__ import annotations

from mva.tools.base import FunctionTool, SecurityCheck, Tool, ToolResult
from mva.tools.registry import (
    ToolRegistry,
    execute_tool,
    get_default_registry,
    get_tool_defs,
)
from mva.tools.builtin import register_all as _register_builtins

__all__ = [
    "FunctionTool",
    "SecurityCheck",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "execute_tool",
    "get_default_registry",
    "get_tool_defs",
]


# ---------------------------------------------------------------------------
# Backward-compatible @_register decorator
# ---------------------------------------------------------------------------


def _register(
    name: str,
    description: str,
    parameters: dict,
    *,
    prompt_snippet: str | None = None,
):
    """Decorator to register a function as a tool (backward compat).

    New code should subclass :class:`Tool` instead.
    """
    return get_default_registry().register_fn(
        name=name,
        description=description,
        parameters=parameters,
        prompt_snippet=prompt_snippet,
    )


# ---------------------------------------------------------------------------
# Initialise default registry with built-in tools
# ---------------------------------------------------------------------------

_registry = get_default_registry()
if not _registry.list_tools():
    _register_builtins(_registry)
    # Discover external tools
    _registry.discover_entry_points()
    _registry.discover_walk_up(".mva/tools")
    home_tools = __import__("pathlib").Path.home() / ".mva" / "tools"
    _registry.discover_dirs(str(home_tools))

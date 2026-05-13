"""Built-in tools for MVA.

Call :func:`register_all` to populate a :class:`~mva.agent.tools.registry.ToolRegistry`
with all standard tools.
"""

from __future__ import annotations

from mva_core.tools.registry import ToolRegistry

from .bash import BashTool
from .edit import EditTool
from .fetch_url import FetchUrlTool
from .list_files import ListFilesTool
from .read import ReadTool
from .write import WriteTool


def register_all(registry: ToolRegistry) -> None:
    """Register all built-in tools on *registry*."""
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(FetchUrlTool())
    registry.register(ListFilesTool())
    registry.register(BashTool())

    # 'ls' alias — same executor, distinct tool definition
    from mva_core.tools import ToolDef

    ls_def = ToolDef(
        name="ls",
        description=(
            "Alias for list_files: List files and directories in a given "
            "path. Supports recursive listing."
        ),
        parameters=ListFilesTool.parameters,
    )
    # Register ls as a FunctionTool wrapping the ListFilesTool executor
    from mva_core.tools.base import FunctionTool

    ls_fn = ListFilesTool().execute
    registry.register(
        FunctionTool(
            name="ls",
            description=ls_def.description,
            parameters=ls_def.parameters,
            fn=ls_fn,
            prompt_snippet="List files and directories",
        )
    )

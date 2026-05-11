"""Base types for the MVA tool system.

Defines the core abstractions that all tools share:

* :class:`ToolDef` — API-facing definition of a callable function
* :class:`Tool` — abstract base class for all tools
* :class:`ToolResult` — result of executing a tool
* :class:`SecurityCheck` — outcome of a security evaluation
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# ToolDef
# ---------------------------------------------------------------------------


@dataclass
class ToolDef:
    """Definition of a tool (function) the model can call.

    Sent to the OpenAI-compatible API as part of the ``tools`` parameter
    in chat completion requests.
    """

    name: str
    """Tool identifier (must match the registered tool name)."""

    description: str
    """Human-readable description shown to the LLM."""

    parameters: dict[str, Any]
    """JSON Schema describing the tool's arguments."""


# ---------------------------------------------------------------------------
# Security Check
# ---------------------------------------------------------------------------


@dataclass
class SecurityCheck:
    """Result of a path / operation security check."""

    safe: bool
    """``True`` if the operation is safe to proceed without confirmation."""

    message: str = ""
    """Human-readable explanation of the risk (for the confirmation prompt)."""

    offending_path: str = ""
    """The specific path that triggered the warning."""


# ---------------------------------------------------------------------------
# Tool Result
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Result of executing a tool call."""

    content: str
    """Text returned to the LLM."""

    is_error: bool = False
    """Whether the operation failed."""

    # -- confirmation support --
    needs_confirmation: bool = False
    """If ``True``, the REPL must prompt the user before proceeding."""

    confirmation_message: str = ""
    """Message shown to the user during the confirmation prompt."""

    confirmation_tool: str = ""
    """Tool name to re-invoke after confirmation."""

    confirmation_args: dict[str, Any] | None = None
    """Arguments to re-invoke the tool with after confirmation."""


# ---------------------------------------------------------------------------
# Tool ABC
# ---------------------------------------------------------------------------


class Tool(ABC):
    """Abstract base class for all MVA tools.

    Subclasses must set *name*, *description*, and *parameters* as class
    attributes and implement :meth:`execute`.

    Optional class attributes:
        *prompt_snippet* — short one-liner for the system prompt (falls
        back to first sentence of *description*).
    """

    name: str
    """Unique tool identifier (used in tool calls)."""

    description: str
    """Full description sent to the LLM via the API tool definition."""

    parameters: dict[str, Any]
    """JSON Schema for the tool's arguments."""

    prompt_snippet: str | None = None
    """Optional one-liner for the system prompt's tool list."""

    def to_tool_def(self) -> ToolDef:
        """Convert this tool into a :class:`ToolDef` for the API."""
        return ToolDef(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given keyword arguments.

        Receives the parsed arguments from the LLM tool call.  The
        special ``_confirmed`` keyword is injected by the registry when
        the user has approved a security-sensitive operation — the tool
        can use it to skip its own internal security checks on the
        second invocation.
        """
        ...

    def check_security(self, **kwargs: Any) -> SecurityCheck | None:
        """Evaluate whether this operation needs user confirmation.

        Called by the :class:`ToolRegistry` before :meth:`execute` when
        ``_confirmed`` is ``False``.  Return ``None`` if the operation
        is safe to proceed without confirmation, or a
        :class:`SecurityCheck` describing the risk.

        The default implementation returns ``None`` (always safe).
        """
        return None


# ---------------------------------------------------------------------------
# Function-based tool adapter (backward compat with @_register)
# ---------------------------------------------------------------------------


class FunctionTool(Tool):
    """Adapter that wraps a plain function as a :class:`Tool`.

    Used internally by the ``@_register`` decorator so existing
    function-based tools continue to work without changes.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        fn: Any,
        *,
        prompt_snippet: str | None = None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.prompt_snippet = prompt_snippet
        self._fn = fn

    def execute(self, **kwargs: Any) -> ToolResult:
        result = self._fn(**kwargs)
        if isinstance(result, ToolResult):
            return result
        return ToolResult(content=str(result))

    def check_security(self, **kwargs: Any) -> SecurityCheck | None:
        """Function tools handle security internally; registry skips check."""
        return None

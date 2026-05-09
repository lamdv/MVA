"""Tool registry with multi-source discovery.

The :class:`ToolRegistry` is the central hub for all tools.  It supports
registration from:

* **Built-in tools** — imported explicitly at startup
* **Entry points** — tools installed via pip (``mva.tools`` group)
* **Project directories** — ``.mva/tools/`` walking up from CWD
* **Global directory** — ``~/.mva/tools/``
* **Explicit paths** — ``--skill`` / ``--tool`` CLI flags (future)

A module-level singleton is available for backward compatibility with
``get_tool_defs()`` and ``execute_tool()``.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import sys
from pathlib import Path
from typing import Any

from mva.tools.base import FunctionTool, SecurityCheck, Tool, ToolResult


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Central registry for MVA tools with discovery from multiple sources."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # -- Registration ------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a tool instance.  Later registrations for the same
        *name* overwrite earlier ones (closest wins)."""
        self._tools[tool.name] = tool

    def register_fn(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        *,
        prompt_snippet: str | None = None,
    ):
        """Decorator that wraps a function in a :class:`FunctionTool`.

        Backward-compatible replacement for the old ``@_register``.
        """

        def decorator(fn):
            self.register(
                FunctionTool(
                    name=name,
                    description=description,
                    parameters=parameters,
                    fn=fn,
                    prompt_snippet=prompt_snippet,
                )
            )
            return fn

        return decorator

    # -- Discovery ---------------------------------------------------------

    def discover_entry_points(self) -> None:
        """Load tools from the ``mva.tools`` entry-point group.

        Any pip-installed package can expose tools by declaring::

            [project.entry-points."mva.tools"]
            my_tool = "my_package.module:MyToolClass"

        The entry point value can reference:

        * A :class:`Tool` subclass — instantiated and registered.
        * A module — scanned for both class-based and imperative tools.
        """
        try:
            eps = importlib.metadata.entry_points(group="mva.tools")
        except TypeError:
            # Python < 3.12 fallback
            try:
                eps = importlib.metadata.entry_points().get("mva.tools", [])
            except Exception:
                return

        for ep in eps:
            try:
                obj = ep.load()
            except Exception:
                continue

            if isinstance(obj, type) and issubclass(obj, Tool):
                try:
                    self.register(obj())
                except Exception:
                    pass
            elif isinstance(obj, Tool):
                self.register(obj)
            elif hasattr(obj, "__name__") and not callable(obj):
                # It's a module — scan it for both styles
                tool = _tool_from_module(obj, ep.name)
                if tool is not None:
                    self.register(tool)
                else:
                    # Fallback: scan for Tool subclasses in the module
                    for attr_name in dir(obj):
                        attr = getattr(obj, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, Tool)
                            and attr is not Tool
                            and attr is not FunctionTool
                        ):
                            try:
                                self.register(attr())
                            except Exception:
                                pass

    def discover_dirs(self, *dirs: str | Path) -> None:
        """Scan directories for ``.py`` files containing :class:`Tool` subclasses.

        Each ``.py`` file is imported as a module.  Any :class:`Tool`
        subclass found in the module's namespace is instantiated and
        registered.  Files starting with ``_`` are skipped.
        """
        for dirpath in dirs:
            path = Path(dirpath).expanduser().resolve()
            if not path.is_dir():
                continue
            self._scan_dir(path)

    def discover_walk_up(self, relative_dir: str = ".mva/tools") -> None:
        """Walk from CWD up through parents, scanning each
        *relative_dir* found.  Closest to CWD wins on name conflicts."""
        dirs = _walk_up_dirs(Path.cwd(), relative_dir)
        # Reverse so closest (CWD) is scanned last and wins
        for d in reversed(dirs):
            self._scan_dir(d)

    # -- Query -------------------------------------------------------------

    def get(self, name: str) -> Tool | None:
        """Return the registered tool with *name*, or ``None``."""
        return self._tools.get(name)

    def list_defs(self) -> list[Any]:
        """Return :class:`~mva.llm.ToolDef` objects for all registered tools.

        Aliases (different name, same underlying tool) are included as
        separate definitions.
        """
        return [t.to_tool_def() for t in self._tools.values()]

    def list_tools(self) -> list[Tool]:
        """Return all registered :class:`Tool` instances."""
        return list(self._tools.values())

    @property
    def tool_names(self) -> list[str]:
        """Sorted list of registered tool names."""
        return sorted(self._tools)

    # -- Execution ---------------------------------------------------------

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        confirmed: bool = False,
    ) -> ToolResult:
        """Execute a tool by name, with automatic security gating.

        When *confirmed* is ``False``, :meth:`Tool.check_security` is
        called first.  If it reports unsafe, a ``needs_confirmation``
        :class:`ToolResult` is returned so the REPL can prompt the user.
        On the second call (with *confirmed*=``True``), security is
        skipped and the tool executes directly.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                content=(
                    f"Error: Unknown tool '{name}'."
                    f" Available: {', '.join(sorted(self._tools))}"
                ),
                is_error=True,
            )

        try:
            if confirmed:
                arguments = {**arguments, "_confirmed": True}
            else:
                # Security gate
                check = tool.check_security(**arguments)
                if check is not None and not check.safe:
                    return _confirm_result(check, tool.name, **arguments)

            result = tool.execute(**arguments)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(content=str(result))
        except Exception as exc:
            return ToolResult(
                content=f"Error executing '{name}': {exc}",
                is_error=True,
            )

    # -- Lifecycle ---------------------------------------------------------

    def reload(self) -> None:
        """Clear all tools and re-discover from scratch."""
        self._tools.clear()

    def unregister(self, name: str) -> bool:
        """Remove a tool by name.  Returns ``True`` if it was registered."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    # -- Internals ---------------------------------------------------------

    def _scan_dir(self, path: Path) -> None:
        """Import ``.py`` files in *path* and register any tools found.

        Detects two styles:

        * **Class-based** — a :class:`Tool` subclass anywhere in the module.
        * **Imperative** — module-level ``name``, ``description``,
          ``parameters``, and ``execute()`` function.
        """
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

        for py_file in sorted(path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            try:
                spec = importlib.util.spec_from_file_location(
                    f"mva_ext_{module_name}", py_file
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue

            # -- Style A: Tool subclass(es) in the module ------------------
            found_class = False
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Tool)
                    and attr is not Tool
                    and attr is not FunctionTool
                ):
                    try:
                        self.register(attr())
                        found_class = True
                    except Exception:
                        pass

            # -- Style B: imperative module ---------------------------------
            if not found_class:
                tool = _tool_from_module(mod, module_name)
                if tool is not None:
                    self.register(tool)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _walk_up_dirs(start: Path, relative_dir: str) -> list[Path]:
    """Walk from *start* up to root, collecting *relative_dir* if it exists."""
    candidates: list[Path] = []
    current = start.resolve()
    root = Path(current.anchor)

    while True:
        d = current / relative_dir
        if d.is_dir():
            candidates.append(d)
        if current == root:
            break
        current = current.parent

    return candidates  # most distant first, CWD last


def _tool_from_module(mod: Any, fallback_name: str) -> Tool | None:
    """Inspect a module for the imperative tool convention.

    A module is a valid imperative tool if it has **module-level**:

    * ``name`` — ``str``, tool identifier
    * ``description`` — ``str``, sent to the LLM
    * ``parameters`` — ``dict``, JSON Schema for arguments
    * ``execute(**kwargs)`` — callable, returns ``str``, ``dict``, or
      :class:`ToolResult`

    Optional module-level attributes:

    * ``prompt_snippet`` — ``str``, one-liner for the system prompt
    * ``check_security(**kwargs)`` — callable, returns ``None`` (safe) or
      a :class:`SecurityCheck` / ``dict`` with ``safe=False``

    Returns a :class:`FunctionTool` wrapping the module, or ``None`` if
    the module doesn't match the convention.
    """
    name = getattr(mod, "name", None)
    description = getattr(mod, "description", None)
    parameters = getattr(mod, "parameters", None)
    execute_fn = getattr(mod, "execute", None)

    if not (isinstance(name, str) and isinstance(description, str)
            and isinstance(parameters, dict) and callable(execute_fn)):
        return None

    prompt_snippet = getattr(mod, "prompt_snippet", None)
    check_fn = getattr(mod, "check_security", None)

    # Wrap execute to normalise return values
    def _wrapped_execute(**kwargs: Any) -> ToolResult:
        result = execute_fn(**kwargs)
        if isinstance(result, ToolResult):
            return result
        if isinstance(result, dict):
            return ToolResult(
                content=str(result.get("content", "")),
                is_error=bool(result.get("is_error", False)),
            )
        return ToolResult(content=str(result))

    tool = FunctionTool(
        name=name,
        description=description,
        parameters=parameters,
        fn=_wrapped_execute,
        prompt_snippet=prompt_snippet,
    )

    # Override check_security if the module provides one
    if callable(check_fn):
        def _wrapped_check(**kwargs: Any) -> SecurityCheck | None:
            result = check_fn(**kwargs)
            if result is None:
                return None
            if isinstance(result, SecurityCheck):
                return result
            if isinstance(result, dict):
                return SecurityCheck(
                    safe=bool(result.get("safe", True)),
                    message=str(result.get("message", "")),
                    offending_path=str(result.get("offending_path", "")),
                )
            return None

        # Attach as instance method override
        tool.check_security = _wrapped_check  # type: ignore[method-assign]

    return tool


def _confirm_result(
    check: SecurityCheck,
    tool_name: str,
    **args: Any,
) -> ToolResult:
    """Build a ``needs_confirmation`` result for a security warning."""
    return ToolResult(
        content="",
        needs_confirmation=True,
        confirmation_message=(
            f"Security check: {check.message}\n"
            f"  Tool: {tool_name}\n"
            f"  Allow this operation to proceed?"
        ),
        confirmation_tool=tool_name,
        confirmation_args=args,
    )


# ---------------------------------------------------------------------------
# Singleton (backward compat)
# ---------------------------------------------------------------------------

_default_registry: ToolRegistry | None = None


def get_default_registry() -> ToolRegistry:
    """Return (or create) the module-level default registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
    return _default_registry


def get_tool_defs() -> list[Any]:
    """Backward-compatible: return all tool definitions from the default registry."""
    return get_default_registry().list_defs()


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    confirmed: bool = False,
) -> ToolResult:
    """Backward-compatible: execute a tool from the default registry."""
    return get_default_registry().execute(name, arguments, confirmed=confirmed)

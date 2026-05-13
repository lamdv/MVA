"""REPL Plugin system for MVA.

Plugins allow external code to hook into the REPL lifecycle without
modifying ``repl.py`` directly.

Discovery
---------
Plugins are discovered from two sources (in order, all are loaded):

1. **Entry points** — packages declaring ``mva.repl_plugins`` in their
   ``pyproject.toml``::

    [project.entry-points."mva.repl_plugins"]
    my_plugin = "my_package.plugin:MyPlugin"

2. **``.mva/plugins/`` directory** — project-local Python files or
   packages.  Each file is imported and scanned for :class:`REPLPlugin`
   subclasses (singletons only).

Usage (inside a plugin)::

    from __future__ import annotations
    from mva.cli.plugins import REPLPlugin

    class MyPlugin(REPLPlugin):
        name = "my_plugin"
        description = "Does something interesting"

        def on_startup(self, session, console):
            console.print("[dim]MyPlugin loaded.[/]")

        def on_pre_message(self, raw: str) -> str:
            # Transform user input
            return raw.upper()

        def on_event(self, event: dict) -> None:
            # Tap into streaming events
            if event.get("type") == "tool_call":
                print(f"  [dim](plugin saw: {event['name']})[/]")

        def on_shutdown(self) -> None:
            pass
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console
    from mva.agent import Session


# ---------------------------------------------------------------------------
# Plugin base class
# ---------------------------------------------------------------------------


class REPLPlugin:
    """Base class for MVA REPL plugins.

    Subclass this and override the hook methods you need.  All hooks are
    optional — the default implementations are no-ops.

    Each plugin instance is a singleton: one instance per discovered class.
    """

    name: str = "unnamed"
    """Display name for the plugin (used in ``/plugins`` output)."""

    description: str = ""
    """Short description of what the plugin does."""

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_startup(self, session: Session, console: Console) -> None:
        """Called once when the REPL starts, after the session is ready.

        Good for initialisation, registering additional commands, or
        printing a greeting.
        """

    def on_pre_prompt(self) -> str | None:
        """Return a custom prompt string, or ``None`` for the default.

        When multiple plugins return a string, the **first** non-None
        result wins (plugins are called in discovery order).
        """

    def on_pre_message(self, raw: str) -> str:
        """Transform the raw user input before processing.

        Receives the trimmed user input.  Return the (possibly modified)
        string.  The default implementation returns *raw* unchanged.
        """
        return raw

    def on_event(self, event: dict[str, Any]) -> None:
        """Tap into session events as they are emitted.

        Called for every event during the tool-calling loop, including
        ``thinking``, ``delta``, ``tool_call``, ``tool_result``,
        ``done``, ``cancelled``, and ``error`` types.

        The event dict is the same one yielded by :class:`Session.chat()`
        and passed to :func:`render_event`.
        """

    def on_shutdown(self) -> None:
        """Called when the REPL exits (cleanup)."""


# ---------------------------------------------------------------------------
# Plugin manager
# ---------------------------------------------------------------------------


class PluginManager:
    """Wraps a list of plugins and delegates lifecycle calls to each.

    Exceptions from individual plugins are caught and printed to stderr
    so one failing plugin cannot take down the REPL.
    """

    def __init__(self, plugins: list[REPLPlugin] | None = None) -> None:
        self.plugins: list[REPLPlugin] = plugins or []

    def on_startup(self, session: Session, console: Console) -> None:
        """Notify all plugins that the REPL has started."""
        for p in self.plugins:
            try:
                p.on_startup(session, console)
            except Exception as exc:
                import sys
                sys.stderr.write(
                    f"[plugin:{p.name}] on_startup error: {exc}\n"
                )

    def on_pre_prompt(self) -> str | None:
        """Get a custom prompt from the first plugin that provides one.

        Returns ``None`` if no plugin overrides the prompt.
        """
        for p in self.plugins:
            try:
                result = p.on_pre_prompt()
                if result is not None:
                    return result
            except Exception as exc:
                import sys
                sys.stderr.write(
                    f"[plugin:{p.name}] on_pre_prompt error: {exc}\n"
                )
        return None

    def on_pre_message(self, raw: str) -> str:
        """Let each plugin transform the user input in sequence."""
        for p in self.plugins:
            try:
                raw = p.on_pre_message(raw)
            except Exception as exc:
                import sys
                sys.stderr.write(
                    f"[plugin:{p.name}] on_pre_message error: {exc}\n"
                )
        return raw

    def on_event(self, event: dict[str, Any]) -> None:
        """Notify all plugins of a session event."""
        for p in self.plugins:
            try:
                p.on_event(event)
            except Exception as exc:
                import sys
                sys.stderr.write(
                    f"[plugin:{p.name}] on_event error: {exc}\n"
                )

    def on_shutdown(self) -> None:
        """Notify all plugins that the REPL is shutting down."""
        for p in self.plugins:
            try:
                p.on_shutdown()
            except Exception as exc:
                import sys
                sys.stderr.write(
                    f"[plugin:{p.name}] on_shutdown error: {exc}\n"
                )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_PLUGIN_DIR_NAME = "plugins"
"""Name of the plugin directory inside ``.mva/``."""


def _walk_up_for_plugins(start: Path) -> list[Path]:
    """Walk from *start* up through parents collecting ``.mva/plugins/`` dirs.

    Returns a list ordered from the most distant ancestor to *start* itself
    (closest last), so that closer plugins take priority in name resolution.
    """
    candidates: list[Path] = []
    current = start.resolve()
    root = current.anchor  # "/" on Unix, "C:\\" on Windows

    while True:
        plugins_dir = current / ".mva" / _PLUGIN_DIR_NAME
        if plugins_dir.is_dir():
            candidates.append(plugins_dir)
        if current == Path(root):
            break
        current = current.parent

    candidates.reverse()  # closest (CWD) last
    return candidates


def _home_plugins_dir() -> Path | None:
    """Return ``~/.mva/plugins/`` if it exists, otherwise ``None``."""
    home = Path.home() / ".mva" / _PLUGIN_DIR_NAME
    return home if home.is_dir() else None


def _discover_from_dir(plugins_dir: Path) -> list[REPLPlugin]:
    """Scan a directory for Python plugins and instantiate REPLPlugin subclasses.

    Supports two layouts:

    * ``plugin_name.py`` — single-file plugin
    * ``plugin_name/__init__.py`` — package-style plugin

    Each file is imported and all :class:`REPLPlugin` subclasses (excluding
    the base class) are instantiated.
    """
    result: list[REPLPlugin] = []
    if not plugins_dir.is_dir():
        return result

    for entry in sorted(plugins_dir.iterdir()):
        plugin_cls: type[REPLPlugin] | None = None

        if entry.suffix == ".py" and entry.stem != "__init__":
            # Single-file plugin
            try:
                spec = importlib.util.spec_from_file_location(
                    f"_mva_plugin_{entry.stem}", entry
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                plugin_cls = _find_plugin_class(mod)
            except Exception:
                continue

        elif entry.is_dir() and (entry / "__init__.py").is_file():
            # Package-style plugin
            try:
                spec = importlib.util.spec_from_file_location(
                    f"_mva_plugin_{entry.name}",
                    entry / "__init__.py",
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                plugin_cls = _find_plugin_class(mod)
            except Exception:
                continue

        if plugin_cls is not None:
            try:
                result.append(plugin_cls())
            except Exception:
                continue

    return result


def _find_plugin_class(module: object) -> type[REPLPlugin] | None:
    """Find the first :class:`REPLPlugin` subclass in a module."""
    for name in dir(module):
        obj = getattr(module, name, None)
        if (
            isinstance(obj, type)
            and issubclass(obj, REPLPlugin)
            and obj is not REPLPlugin
        ):
            return obj
    return None


def discover_plugins(
    *,
    extra_dirs: list[str] | None = None,
    no_plugins: bool = False,
) -> list[REPLPlugin]:
    """Discover all available plugins and return instantiated list.

    Parameters
    ----------
    extra_dirs:
        Additional directories to scan for plugin files (resolved as-is,
        no parent-walking).
    no_plugins:
        When ``True``, return an empty list.

    Returns
    -------
    A list of instantiated :class:`REPLPlugin` objects.  Plugins from
    closer directories (CWD) appear after more distant ones so that
    closer plugins can shadow.
    """
    if no_plugins:
        return []

    if os.environ.get("MVA_NO_PLUGINS", "").strip() in ("1", "true", "yes"):
        return []

    seen_names: set[str] = set()
    all_plugins: list[REPLPlugin] = []

    # 1. Entry points — from installed packages
    try:
        for ep in importlib.metadata.entry_points(group="mva.repl_plugins"):
            try:
                cls = ep.load()
                if (
                    isinstance(cls, type)
                    and issubclass(cls, REPLPlugin)
                    and cls is not REPLPlugin
                ):
                    plugin = cls()
                    if plugin.name not in seen_names:
                        seen_names.add(plugin.name)
                        all_plugins.append(plugin)
            except Exception:
                continue
    except Exception:
        pass

    # 2. Global plugins (~/.mva/plugins/) — loaded first, overridable
    home_dir = _home_plugins_dir()
    if home_dir is not None:
        for plugin in _discover_from_dir(home_dir):
            if plugin.name not in seen_names:
                seen_names.add(plugin.name)
                all_plugins.append(plugin)

    # 3. Project plugins walking up from CWD — closest wins on name conflict
    for plugins_dir in _walk_up_for_plugins(Path.cwd()):
        for plugin in _discover_from_dir(plugins_dir):
            if plugin.name not in seen_names:
                seen_names.add(plugin.name)
                all_plugins.append(plugin)

    # 4. Extra directories
    if extra_dirs:
        for dirpath in extra_dirs:
            path = Path(dirpath).expanduser().resolve()
            if path.is_dir():
                for plugin in _discover_from_dir(path):
                    if plugin.name not in seen_names:
                        seen_names.add(plugin.name)
                        all_plugins.append(plugin)

    return all_plugins

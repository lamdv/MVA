"""MVA CLI — interactive REPL harness.

Split into submodules:

- ``app.py`` — Typer app entrypoint, single-run (``--print``) mode
- ``console.py`` — prompt-toolkit session, completer, key bindings
- ``repl.py`` — interactive REPL loop, turn handler, confirmation
- ``renderer.py`` — streaming delta display
- ``plugins/`` — REPL plugin system (``REPLPlugin``, ``PluginManager``)
"""

from mva.cli.app import _app

__all__ = ["_app"]

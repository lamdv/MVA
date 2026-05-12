"""Example REPL plugin — logs every turn to a timestamped file.

Demonstrates all lifecycle hooks:
- ``on_startup`` — opens a log file with a header
- ``on_pre_message`` — writes user input to the log
- ``on_event`` — captures streaming deltas and tool calls
- ``on_shutdown`` — closes the log file with a footer

Enable by saving to ``.mva/plugins/`` or installing via entry point.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from mva.cli.plugins import REPLPlugin


class TurnLogger(REPLPlugin):
    """Log all REPL interactions to a file in /tmp."""

    name = "turn_logger"
    description = "Log all conversation turns to /tmp/mva_turn_log.txt"

    def __init__(self) -> None:
        self._log_file: str | None = None
        self._buffer: str = ""

    def on_startup(self, session, console) -> None:  # noqa: ANN001
        session_dir = session.current_provider or "unknown"
        self._log_file = os.path.join(
            "/tmp", f"mva_turn_log_{session_dir}_{os.getpid()}.txt"
        )
        with open(self._log_file, "a") as f:
            f.write(
                f"=== MVA Session started at "
                f"{datetime.now(timezone.utc).isoformat()} ===\n"
            )
        console.print(f"[dim]📝 TurnLogger → {self._log_file}[/]")

    def on_pre_message(self, raw: str) -> str:
        self._buffer = ""
        with open(self._log_file, "a") as f:
            f.write(f"\n>>> USER: {raw}\n")
        return raw

    def on_event(self, event: dict) -> None:  # noqa: ANN001
        etype = event.get("type")
        content = event.get("content", "")
        with open(self._log_file, "a") as f:
            if etype == "thinking":
                f.write(f"[[thinking]] {content}")
            elif etype == "delta":
                f.write(content)
            elif etype == "tool_call":
                f.write(
                    f"\n[[tool_call]] {event.get('name', '?')}"
                    f"({event.get('args', {})})\n"
                )
            elif etype == "tool_result":
                preview = content[:200]
                status = "OK" if not event.get("is_error") else "ERROR"
                f.write(f"\n[[tool_result {status}]] {preview}\n")
            elif etype == "done":
                f.write("\n[[done]]\n")

    def on_shutdown(self) -> None:
        if self._log_file:
            with open(self._log_file, "a") as f:
                f.write(
                    f"=== Session ended at "
                    f"{datetime.now(timezone.utc).isoformat()} ===\n\n"
                )

"""``bash`` tool — sandboxed shell command execution."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mva_core.tools.base import SecurityCheck, Tool, ToolResult
from mva_core.tools.path_security import check_bash_escape

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_OUTPUT_LINES = 2000
_MAX_OUTPUT_BYTES = 50 * 1024

# Resolve the user's current shell (defaults to /bin/bash if $SHELL is unset)
_CURRENT_SHELL: str = os.environ.get("SHELL", "/bin/bash")

_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+[/~]", "rm -rf on root/home"),
    (r"\bmkfs\.", "filesystem formatting (mkfs)"),
    (r"\bdd\s+if=.+of=/dev", "raw device writes (dd)"),
    (r"\bsudo\b", "privilege escalation (sudo)"),
    (r"\bsu\b", "switch user (su)"),
    (r":\(\)\s*\{.*:\|.*:\|.*&.*;.*;.*\}", "fork bomb"),
    (r"curl.*\|.*(?:ba)?sh", "curl-pipe-shell"),
    (r"wget.*\|.*(?:ba)?sh", "wget-pipe-shell"),
    (r"nc\s+-[lL].*-e", "netcat backdoor"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_resource_limits() -> None:
    """Apply per-process resource limits (Linux/Unix only)."""
    try:
        import resource

        mb = 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (512 * mb, 512 * mb))
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
        resource.setrlimit(resource.RLIMIT_FSIZE, (50 * mb, 50 * mb))
    except (ImportError, ValueError, OSError):
        pass


def _kill_process_tree(pid: int) -> None:
    """Kill the entire process group rooted at *pid*."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def _sanitize_output(text: str) -> str:
    """Strip ANSI escapes and control characters (keep \\t, \\n, \\r)."""
    ansi_re = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    text = ansi_re.sub("", text)
    return "".join(c for c in text if ord(c) >= 0x20 or c in "\t\n\r")


def _truncate_tail(
    content: str, max_lines: int, max_bytes: int
) -> tuple[bool, str]:
    """Keep the **last** *max_lines* / *max_bytes* of *content*."""
    lines = content.split("\n")
    total_lines = len(lines)
    total_bytes = len(content.encode("utf-8"))

    if total_lines <= max_lines and total_bytes <= max_bytes:
        return False, content

    kept: list[str] = []
    kept_bytes = 0
    truncated_by = "lines"

    for line in reversed(lines):
        line_bytes = len(line.encode("utf-8")) + (1 if kept else 0)
        if len(kept) >= max_lines or kept_bytes + line_bytes > max_bytes:
            truncated_by = "lines" if len(kept) >= max_lines else "bytes"
            break
        kept.append(line)
        kept_bytes += line_bytes

    kept.reverse()
    result = "\n".join(kept)
    marker = (
        f"[Output truncated — showing last {len(kept)} of {total_lines} lines "
        f"({truncated_by} limit)]"
    )
    return True, marker + "\n" + result


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class BashTool(Tool):
    name = "bash"
    description = (
        "Execute a bash command in the current working directory. "
        "Returns stdout and stderr. Output is truncated to last "
        f"{_MAX_OUTPUT_LINES} lines or {_MAX_OUTPUT_BYTES // 1024}KB "
        "(whichever is hit first). If truncated, full output is saved "
        "to a temp file. Optionally provide a timeout in seconds."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Bash command to execute",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (optional, no default timeout)",
            },
        },
        "required": ["command"],
    }
    prompt_snippet = "Execute a bash command"

    def check_security(self, command: str, **kwargs: Any) -> SecurityCheck | None:
        # Layer 0: blocklist
        for pattern, label in _DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return SecurityCheck(
                    safe=False,
                    message=f"Dangerous command pattern: {label}",
                    offending_path=command,
                )

        # Layer 1: path escape
        check = check_bash_escape(command, str(Path.cwd()))
        return None if check.safe else check

    def execute(
        self,
        command: str,
        timeout: float | None = None,
        _confirmed: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        cwd = str(Path.cwd())

        sandbox_env: dict[str, str] = {
            "HOME": cwd,
            "PATH": "/usr/bin:/bin:/usr/local/bin:/usr/sbin:/sbin",
            "PWD": cwd,
            "USER": os.environ.get("USER", "user"),
            "LANG": "C.UTF-8",
            "SHELL": _CURRENT_SHELL,
            "TERM": "dumb",
        }

        try:
            proc = subprocess.Popen(
                [_CURRENT_SHELL, "-c", command],
                cwd=cwd,
                env=sandbox_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=_set_resource_limits,
                start_new_session=True,
            )
        except FileNotFoundError:
            return ToolResult(
                content=f"Error: {_CURRENT_SHELL} not found on this system.",
                is_error=True,
            )
        except Exception as exc:
            return ToolResult(
                content=f"Error spawning process: {exc}",
                is_error=True,
            )

        timed_out = False
        raw_output = b""

        _timeout = timeout if timeout else 30  # default 30s safety net
        try:
            raw_output, _ = proc.communicate(timeout=_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc.pid)
            try:
                raw_output, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                _kill_process_tree(proc.pid)
                try:
                    raw_output, _ = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        except Exception:
            _kill_process_tree(proc.pid)
            try:
                raw_output, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        exit_code = proc.returncode
        full_output = raw_output.decode("utf-8", errors="replace")
        full_output = _sanitize_output(full_output)

        was_truncated, final_output = _truncate_tail(
            full_output, _MAX_OUTPUT_LINES, _MAX_OUTPUT_BYTES
        )

        full_path: str | None = None
        if was_truncated:
            fd, full_path = tempfile.mkstemp(prefix="mva-bash-", suffix=".log")
            with os.fdopen(fd, "w") as f:
                f.write(full_output)

        suffix = ""
        if timed_out:
            suffix += f"\n[Command timed out after {_timeout}s]"
        if exit_code not in (None, 0):
            suffix += f"\n[Exited with code {exit_code}]"
        if full_path:
            suffix += f"\n[Full output saved to: {full_path}]"

        is_error = timed_out or (exit_code not in (None, 0))
        return ToolResult(content=final_output + suffix, is_error=is_error)

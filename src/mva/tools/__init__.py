"""Built-in tool definitions and executors for the MVA chatbot.

Tools follow the OpenAI function calling convention. Each tool exports:
- A :class:`ToolDef` for the LLM client
- An ``execute()`` coroutine/function that takes the parsed arguments dict
  and returns a result string.

Security: all file-access tools and the bash tool run a directory-escape check
(via :mod:`mva.tools.path_security`) before executing.  If the operation would
reach outside the current working directory the tool returns a
``needs_confirmation`` result so the REPL can prompt the user.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mva.llm import ToolDef
from mva.tools.path_security import (
    SecurityCheck,
    check_bash_escape,
    check_file_path_escape,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Result of executing a tool call."""
    content: str
    is_error: bool = False

    # -- confirmation support --
    needs_confirmation: bool = False
    confirmation_message: str = ""
    confirmation_tool: str = ""
    confirmation_args: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

# Maps tool name → (ToolDef, executor function)
_registry: dict[str, tuple[ToolDef, Any]] = {}


def _register(name: str, description: str, parameters: dict[str, Any]):
    """Decorator to register a tool function."""
    def decorator(fn):
        _registry[name] = (ToolDef(name=name, description=description, parameters=parameters), fn)
        return fn
    return decorator


def get_tool_defs() -> list[ToolDef]:
    """Return all registered tool definitions (deduplicated by name)."""
    seen: set[str] = set()
    result: list[ToolDef] = []
    for td, _ in _registry.values():
        if td.name not in seen:
            seen.add(td.name)
            result.append(td)
    return result


def execute_tool(name: str, arguments: dict[str, Any], *, confirmed: bool = False) -> ToolResult:
    """Execute a registered tool by name with the given arguments.

    When *confirmed* is ``True`` the internal ``_confirmed=True`` flag is
    injected into *arguments* before calling the tool, allowing tools to
    skip their security checks on the second invocation.
    """
    entry = _registry.get(name)
    if entry is None:
        return ToolResult(
            content=f"Error: Unknown tool '{name}'. Available: {', '.join(sorted(_registry))}",
            is_error=True,
        )
    _, fn = entry
    try:
        if confirmed:
            arguments = {**arguments, "_confirmed": True}
        result = fn(**arguments)
        return result if isinstance(result, ToolResult) else ToolResult(content=str(result))
    except Exception as exc:
        return ToolResult(content=f"Error executing '{name}': {exc}", is_error=True)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@_register(
    name="read",
    description="Read the contents of a file. Supports text files and images (jpg, png, gif, webp). For text files, output is truncated to 2000 lines or 50KB. Use offset/limit for large files.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (relative or absolute).",
            },
            "offset": {
                "type": "number",
                "description": "Line number to start reading from (1-indexed).",
            },
            "limit": {
                "type": "number",
                "description": "Maximum number of lines to read.",
            },
        },
        "required": ["path"],
    },
)
def tool_read(path: str, offset: int = 1, limit: int | None = None,
              _confirmed: bool = False) -> ToolResult:
    # --- Directory escape check ---
    if not _confirmed:
        check = check_file_path_escape(path, str(Path.cwd()), operation="read")
        if not check.safe:
            return _confirm_request(check, "read", path=path, offset=offset, limit=limit)

    p = Path(path)
    if not p.exists():
        return ToolResult(content=f"Error: File not found: {path}", is_error=True)
    if not p.is_file():
        return ToolResult(content=f"Error: Not a file: {path}", is_error=True)

    # Image detection
    suffix = p.suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return ToolResult(content=f"(image at {path})")

    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        return ToolResult(content=f"Error reading {path}: {exc}", is_error=True)

    total = len(lines)
    start = max(0, offset - 1)
    if limit is not None:
        end = min(total, start + limit)
    else:
        end = min(total, start + 2000)

    result_lines = lines[start:end]
    content = "".join(result_lines)

    # 50KB cap
    max_bytes = 50 * 1024
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
        truncated += f"\n\n[Truncated at {max_bytes // 1024}KB]"
        return ToolResult(content=truncated)

    if end < total:
        content += f"\n\n[Lines {start+1}-{end} of {total}]"
    return ToolResult(content=content)


@_register(
    name="write",
    description="Write content to a file. Creates the file if it doesn't exist, overwrites if it does. Automatically creates parent directories.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write (relative or absolute).",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file.",
            },
        },
        "required": ["path", "content"],
    },
)
def tool_write(path: str, content: str, _confirmed: bool = False) -> ToolResult:
    # --- Directory escape check ---
    if not _confirmed:
        check = check_file_path_escape(path, str(Path.cwd()), operation="write")
        if not check.safe:
            return _confirm_request(check, "write", path=path, content=content)

    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult(content=f"Successfully wrote {len(content)} bytes to {path}")
    except Exception as exc:
        return ToolResult(content=f"Error writing {path}: {exc}", is_error=True)


@_register(
    name="list_files",
    description="List files and directories in a given path. Supports recursive listing up to a specified depth (depth: recursion depth, starting from 1).",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list (relative or absolute). Defaults to current working directory.",
            },
            "depth": {
                "type": "number",
                "description": "Recursion depth for listing (1 = top-level only). Defaults to 2.",
            },
            "limit": {
                "type": "number",
                "description": "Maximum number of entries to return. Defaults to 200.",
            },
        },
        "required": [],
    },
)
def tool_list_files(path: str = ".", depth: int = 2, limit: int = 200,
                    _confirmed: bool = False) -> ToolResult:
    # --- Directory escape check ---
    if not _confirmed:
        check = check_file_path_escape(path, str(Path.cwd()), operation="list")
        if not check.safe:
            return _confirm_request(
                check, "list_files", path=path, depth=depth, limit=limit,
            )

    p = Path(path)
    if not p.exists():
        return ToolResult(content=f"Error: Directory not found: {path}", is_error=True)
    if not p.is_dir():
        return ToolResult(content=f"Error: Not a directory: {path}", is_error=True)

    entries: list[str] = []
    depth = max(1, min(depth, 5))
    limit = max(1, min(limit, 1000))

    try:
        for current_depth in range(1, depth + 1):
            pattern = "*/" * (current_depth - 1) + "*"
            for item in sorted(p.glob(pattern)):
                if len(entries) >= limit:
                    entries.append(f"... (truncated at {limit} entries)")
                    return ToolResult(content="\n".join(entries))
                rel = item.relative_to(p)
                prefix = "📁 " if item.is_dir() else "📄 "
                entries.append(f"{prefix}{rel}")
    except Exception as exc:
        return ToolResult(content=f"Error listing {path}: {exc}", is_error=True)

    if not entries:
        return ToolResult(content=f"(empty directory: {p})")
    return ToolResult(content="\n".join(entries))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _confirm_request(
    check: SecurityCheck,
    tool_name: str,
    **args: Any,
) -> ToolResult:
    """Build a ``needs_confirmation`` response for a path-escape warning."""
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
# Bash tool (with full safety stack)
# ---------------------------------------------------------------------------

#: Maximum output lines retained (tail-based truncation).
_BASH_MAX_OUTPUT_LINES = 2000
#: Maximum output bytes retained (50 KB).
_BASH_MAX_OUTPUT_BYTES = 50 * 1024

# Patterns that are unconditionally blocked (must not run, ever).
_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+[/~]",                   "rm -rf on root/home"),
    (r"\bmkfs\.",                           "filesystem formatting (mkfs)"),
    (r"\bdd\s+if=.+of=/dev",               "raw device writes (dd)"),
    (r"\bsudo\b",                           "privilege escalation (sudo)"),
    (r"\bsu\b",                             "switch user (su)"),
    (r":\(\)\s*\{.*:\|.*:\|.*&.*;.*;.*\}", "fork bomb"),
    (r"curl.*\|.*(?:ba)?sh",               "curl-pipe-shell"),
    (r"wget.*\|.*(?:ba)?sh",               "wget-pipe-shell"),
    (r"nc\s+-[lL].*-e",                    "netcat backdoor"),
]


def _set_resource_limits() -> None:
    """Apply per-process resource limits (Linux/Unix only)."""
    try:
        import resource
        mb = 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS,   (256 * mb, 256 * mb))   # 256 MB virtual memory
        resource.setrlimit(resource.RLIMIT_CPU,  (10, 10))              # 10 s CPU time
        resource.setrlimit(resource.RLIMIT_FSIZE,(10 * mb, 10 * mb))    # 10 MB file writes
        resource.setrlimit(resource.RLIMIT_NPROC,(50, 50))              # 50 processes
    except (ImportError, ValueError, OSError):
        pass  # not available on this platform


def _kill_process_tree(pid: int) -> None:
    """Kill the entire process group rooted at *pid*."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def _sanitize_binary_output(text: str) -> str:
    """Strip ANSI escapes and control characters (keep \\t, \\n, \\r)."""
    # Strip ANSI escape sequences
    ansi_re = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
    text = ansi_re.sub('', text)
    # Filter C0 control characters except tab, newline, carriage-return
    return ''.join(
        c for c in text
        if ord(c) >= 0x20 or c in '\t\n\r'
    )


def _truncate_tail(content: str, max_lines: int, max_bytes: int) -> tuple[bool, str]:
    """Keep the **last** *max_lines* / *max_bytes* of *content*.

    Returns ``(was_truncated, truncated_content)``.
    """
    lines = content.split('\n')
    total_lines = len(lines)
    total_bytes = len(content.encode('utf-8'))

    if total_lines <= max_lines and total_bytes <= max_bytes:
        return False, content

    # Work backwards
    kept: list[str] = []
    kept_bytes = 0
    truncated_by = 'lines'

    for line in reversed(lines):
        line_bytes = len(line.encode('utf-8')) + (1 if kept else 0)  # +newline
        if len(kept) >= max_lines or kept_bytes + line_bytes > max_bytes:
            if len(kept) >= max_lines:
                truncated_by = 'lines'
            else:
                truncated_by = 'bytes'
            break
        kept.append(line)
        kept_bytes += line_bytes

    kept.reverse()
    result = '\n'.join(kept)

    marker = (
        f"[Output truncated — showing last {len(kept)} of {total_lines} lines "
        f"({truncated_by} limit)]"
    )
    return True, marker + '\n' + result


@_register(
    name="bash",
    description=(
        "Execute a bash command in the current working directory. "
        "Returns stdout and stderr. Output is truncated to last "
        f"{_BASH_MAX_OUTPUT_LINES} lines or {_BASH_MAX_OUTPUT_BYTES // 1024}KB "
        "(whichever is hit first). If truncated, full output is saved to a temp "
        "file. Optionally provide a timeout in seconds."
    ),
    parameters={
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
    },
)
def tool_bash(
    command: str,
    timeout: float | None = None,
    _confirmed: bool = False,
) -> ToolResult:
    """Execute a bash command with defence-in-depth safety."""

    # ---- Layer 0: blocklist (unconditional) -----------------------------
    for pattern, label in _DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return ToolResult(
                content=f"Blocked: dangerous command pattern detected — {label}",
                is_error=True,
            )

    # ---- Layer 1: directory-escape check (with confirmation) -------------
    if not _confirmed:
        check = check_bash_escape(command, str(Path.cwd()))
        if not check.safe:
            return _confirm_request(
                check, "bash", command=command, timeout=timeout,
            )

    # ---- Layer 2: prepare execution environment --------------------------
    cwd = str(Path.cwd())

    # Minimal environment — no LD_PRELOAD, LD_LIBRARY_PATH, PYTHONPATH, etc.
    sandbox_env: dict[str, str] = {
        "HOME": cwd,
        "PATH": "/usr/bin:/bin:/usr/local/bin:/usr/sbin:/sbin",
        "PWD": cwd,
        "USER": os.environ.get("USER", "user"),
        "LANG": "C.UTF-8",
        "SHELL": "/bin/bash",
        "TERM": "dumb",
    }

    # ---- Layer 3: spawn ------------------------------------------------
    try:
        proc = subprocess.Popen(
            ["/bin/bash", "-c", command],
            cwd=cwd,
            env=sandbox_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=_set_resource_limits,  # memory, CPU, file-size, process caps
            start_new_session=True,            # isolate in own process group
        )
    except FileNotFoundError:
        return ToolResult(
            content="Error: /bin/bash not found on this system.",
            is_error=True,
        )
    except Exception as exc:
        return ToolResult(
            content=f"Error spawning process: {exc}",
            is_error=True,
        )

    # ---- Layer 4: read output with timeout ---------------------------
    timed_out = False
    exit_code: int | None = None
    raw_output = b""

    try:
        raw_output, _ = proc.communicate(
            timeout=timeout if timeout is not None else None,
        )
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

    # ---- Layer 5: sanitize + truncate ----------------------------------
    full_output = _sanitize_binary_output(full_output)
    was_truncated, final_output = _truncate_tail(
        full_output, _BASH_MAX_OUTPUT_LINES, _BASH_MAX_OUTPUT_BYTES,
    )

    # Spill full output to temp file if truncated
    full_path: str | None = None
    if was_truncated:
        fd, full_path = tempfile.mkstemp(prefix="mva-bash-", suffix=".log")
        with os.fdopen(fd, "w") as f:
            f.write(full_output)

    # ---- Layer 6: build result -----------------------------------------
    suffix = ""

    if timed_out:
        suffix += f"\n[Command timed out after {timeout}s]"
    if exit_code not in (None, 0):
        suffix += f"\n[Exited with code {exit_code}]"
    if full_path:
        suffix += f"\n[Full output saved to: {full_path}]"

    is_error = timed_out or (exit_code not in (None, 0))
    return ToolResult(content=final_output + suffix, is_error=is_error)


# Also register 'ls' as an alias — share the same executor but with a distinct ToolDef
_ls_def = ToolDef(
    name="ls",
    description="Alias for list_files: List files and directories in a given path. Supports recursive listing.",
    parameters=_registry["list_files"][0].parameters,
)
_registry["ls"] = (_ls_def, tool_list_files)

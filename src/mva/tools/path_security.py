"""Shared path-security checks used by all tools (bash + file tools).

Each check returns a :class:`SecurityCheck` — either ``safe=True`` (proceed)
or ``safe=False`` with a message explaining what path triggered the warning.
The REPL loop then prompts the user for confirmation before executing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from mva.tools.base import SecurityCheck


# ---------------------------------------------------------------------------
# System paths that should never be touched without confirmation
# ---------------------------------------------------------------------------

_BLOCKED_SYSTEM_ROOTS: tuple[str, ...] = (
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/root",
)

_HOME_ESCAPE_PATTERNS: tuple[str, ...] = (
    "~/",
    "~/.ssh",
    "~/.aws",
    "~/.config",
    "$HOME",
    "${HOME}",
)

# System binary directories — safe to reference in bash commands
_ALLOWED_TOOL_PREFIXES: tuple[str, ...] = (
    "/usr/",
    "/bin/",
    "/opt/",
    "/snap/",
    "/lib/",
    "/lib64/",
    "/sbin/",
    "/usr/sbin/",
    "/usr/local/",
)

# Regex for extracting potential paths from bash commands
_PATH_EXTRACTOR = re.compile(r'(?:^|\s)([\w./~-]+)')


# ---------------------------------------------------------------------------
# Bash command check
# ---------------------------------------------------------------------------


def check_bash_escape(command: str, cwd: str) -> SecurityCheck:
    """Check whether a *bash command string* references paths outside *cwd*.

    This is a best-effort static scan of the command text.  It catches most
    accidental escapes (``cat /etc/passwd``, ``find /``, ``cd ~/.ssh``) but
    cannot detect dynamic paths built at runtime (``$var``, ``$(...)``).
    Those are caught by other layers (blocklist regex, rlimits, confirmation).

    Returns ``SecurityCheck(safe=True)`` when the command appears safe, or
    ``SecurityCheck(safe=False)`` with details for the confirmation prompt.
    """
    cwd_resolved = Path(cwd).resolve()

    # -- 1. Absolute system paths ------------------------------------------
    for root in _BLOCKED_SYSTEM_ROOTS:
        if root in command:
            return SecurityCheck(
                safe=False,
                message=f"Command references system path '{root}/...'",
                offending_path=root,
            )

    # -- 2. Home-directory escapes -----------------------------------------
    for pattern in _HOME_ESCAPE_PATTERNS:
        if pattern in command:
            return SecurityCheck(
                safe=False,
                message=f"Command references home directory via '{pattern}'",
                offending_path=pattern,
            )

    # -- 3. Resolve concrete paths found in the command --------------------
    for match in _PATH_EXTRACTOR.finditer(command):
        raw = match.group(1)

        # Skip tokens that don't look like paths
        if not any(c in raw for c in "./~"):
            continue

        # Already caught above
        if raw.startswith("~"):
            continue

        try:
            resolution = _resolve_path(raw, cwd_resolved)
        except Exception:
            continue  # unparseable — let other layers deal with it

        if resolution is None:
            continue

        # Allow system tool binaries
        if _is_system_tool(resolution):
            continue

        # Is it outside CWD?
        try:
            resolution.relative_to(cwd_resolved)
        except ValueError:
            return SecurityCheck(
                safe=False,
                message=(
                    f"Command references path outside working directory:\n"
                    f"  '{raw}' → '{resolution}'"
                ),
                offending_path=raw,
            )

    return SecurityCheck(safe=True)


# ---------------------------------------------------------------------------
# File-path check (read / write / edit / list_files)
# ---------------------------------------------------------------------------


def check_file_path_escape(
    path_str: str,
    cwd: str,
    *,
    operation: str = "access",
) -> SecurityCheck:
    """Check whether a file-system path is inside *cwd*.

    Works for both relative paths (e.g. ``../../other/secrets.env``) and
    absolute paths (e.g. ``/etc/passwd``).  Symlinks are followed, so a
    symlink inside CWD that points outside will be flagged — the user can
    confirm if they truly intend it.

    *operation* is a short label used in the warning message ("read", "write",
    "list", "edit").
    """
    cwd_resolved = Path(cwd).resolve()

    # Expand ~ prefix (Python's Path doesn't do this)
    if path_str.startswith("~"):
        home = Path.home()
        if path_str == "~":
            resolved = home.resolve()
        elif path_str.startswith("~/"):
            resolved = (home / path_str[2:]).resolve()
        else:
            # ~user/... — not supported, flag it
            return SecurityCheck(
                safe=False,
                message=f"Path for {operation} references another user's home: '{path_str}'",
                offending_path=path_str,
            )

        try:
            resolved.relative_to(cwd_resolved)
            return SecurityCheck(safe=True)
        except ValueError:
            return SecurityCheck(
                safe=False,
                message=(
                    f"Path for {operation} is outside working directory:\n"
                    f"  '{path_str}' → '{resolved}'"
                ),
                offending_path=path_str,
            )

    p = Path(path_str)

    # Absolute path
    if p.is_absolute():
        try:
            resolved = p.resolve()
        except Exception:
            return SecurityCheck(
                safe=False,
                message=f"Cannot resolve absolute path for {operation}: '{path_str}'",
                offending_path=path_str,
            )

        try:
            resolved.relative_to(cwd_resolved)
            return SecurityCheck(safe=True)
        except ValueError:
            return SecurityCheck(
                safe=False,
                message=(
                    f"Path for {operation} is outside working directory:\n"
                    f"  '{path_str}' → '{resolved}'"
                ),
                offending_path=path_str,
            )

    # Relative path — resolve against CWD
    try:
        resolved = (cwd_resolved / p).resolve()
    except Exception:
        return SecurityCheck(
            safe=False,
            message=f"Cannot resolve relative path for {operation}: '{path_str}'",
            offending_path=path_str,
        )

    try:
        resolved.relative_to(cwd_resolved)
        return SecurityCheck(safe=True)
    except ValueError:
        return SecurityCheck(
            safe=False,
            message=(
                f"Path for {operation} is outside working directory:\n"
                f"  '{path_str}' → '{resolved}'"
            ),
            offending_path=path_str,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_path(raw: str, cwd: Path) -> Path | None:
    """Resolve a raw path string against CWD.  Returns ``None`` for non-paths."""
    if raw.startswith("/"):
        return Path(raw).resolve()
    return (cwd / raw).resolve()


def _is_system_tool(path: Path) -> bool:
    """Return ``True`` if *path* points to a standard system binary directory."""
    path_str = str(path)
    return any(path_str.startswith(prefix) for prefix in _ALLOWED_TOOL_PREFIXES)

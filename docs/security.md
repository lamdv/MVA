# MVA Security Architecture

This document describes MVA's defence-in-depth security model. Every tool
call — whether reading a file, executing a shell command, or writing to
disk — is gated by a **four-layer security stack** designed to prevent
accidental or malicious damage to the host system.

## Table of Contents

1. [Threat Model](#threat-model)
2. [Layer 0 — Blocklist (Unconditional Deny)](#layer-0--blocklist-unconditional-deny)
3. [Layer 1 — Path Escape Detection](#layer-1--path-escape-detection)
4. [Layer 2 — User Confirmation](#layer-2--user-confirmation)
5. [Layer 3 — Resource Limits & Sandboxing](#layer-3--resource-limits--sandboxing)
6. [End-to-End Flow](#end-to-end-flow)
7. [Per-Tool Security Implementation](#per-tool-security-implementation)
8. [Adding Security to a New Tool](#adding-security-to-a-new-tool)
9. [Key Source Files](#key-source-files)

---

## Threat Model

MVA assumes the following threat model:

- The **LLM is untrusted** — it may attempt to read sensitive files,
  overwrite system configuration, or execute destructive commands.
- The **human user is trusted** — the user is expected to review
  confirmation prompts and exercise judgement.
- The **host system may contain sensitive data** in e.g. `~/.ssh/`,
  `/etc/`, or outside the working directory.
- The goal is **containment** to the working directory (CWD), not
  comprehensive OS-level isolation.

---

## Layer 0 — Blocklist (Unconditional Deny)

**File:** `src/mva/agent/tools/builtin/bash.py`

Before any command is executed, the `BashTool` applies a set of regex
patterns that **unconditionally block** dangerous operations. No user
confirmation can override this layer.

```python
_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+[/~]",          "rm -rf on root/home"),
    (r"\bmkfs\.",                  "filesystem formatting (mkfs)"),
    (r"\bdd\s+if=.+of=/dev",      "raw device writes (dd)"),
    (r"\bsudo\b",                  "privilege escalation (sudo)"),
    (r"\bsu\b",                    "switch user (su)"),
    (r":\(\)\s*\{.*:\|.*:\|.*&.*;.*;.*\}",   "fork bomb"),
    (r"curl.*\|.*(?:ba)?sh",       "curl-pipe-shell"),
    (r"wget.*\|.*(?:ba)?sh",       "wget-pipe-shell"),
    (r"nc\s+-[lL].*-e",           "netcat backdoor"),
]
```

| Pattern | Attack Vector |
|---|---|
| `rm -rf /` or `rm -rf ~` | Deleting entire filesystem or home directory |
| `mkfs.*` | Formatting disk partitions |
| `dd if=... of=/dev/...` | Overwriting block devices directly |
| `sudo` | Escalating to root |
| `su` | Switching to another user |
| Fork bomb (`:(){ :\|:& };:`) | Denial-of-service via process exhaustion |
| `curl ... \| bash` / `wget ... \| bash` | Remote code execution via pipe-to-shell |
| `nc -l -e` | Opening a reverse shell backdoor |

These patterns are checked **before** any path-escape analysis or resource
limiting. If matched, the tool returns an immediate error:

```python
return SecurityCheck(
    safe=False,
    message=f"Dangerous command pattern: {label}",
    offending_path=command,
)
```

---

## Layer 1 — Path Escape Detection

**File:** `src/mva/agent/tools/path_security.py`

All file-system operations (read, write, edit, list_files, bash) are
checked to ensure they stay inside the current working directory (CWD).

### 1.1 Blocked System Roots

These paths are never allowed without confirmation:

```python
_BLOCKED_SYSTEM_ROOTS = (
    "/etc", "/proc", "/sys", "/dev", "/boot", "/root",
)
```

### 1.2 Blocked Home-Escape Patterns

References to home-directory locations are intercepted:

```python
_HOME_ESCAPE_PATTERNS = (
    "~/", "~/.ssh", "~/.aws", "~/.config", "$HOME", "${HOME}",
)
```

### 1.3 Allowed System Tool Prefixes

Certain system binary directories are permitted (referencing tools is
safe; reading/writing their files is caught by other checks):

```python
_ALLOWED_TOOL_PREFIXES = (
    "/usr/", "/bin/", "/opt/", "/snap/", "/lib/", "/lib64/",
    "/sbin/", "/usr/sbin/", "/usr/local/",
)
```

### 1.4 How `check_bash_escape()` Works

1. **String search** for blocked system roots and home patterns in the
   command text.
2. **Regex extraction** of potential path tokens (`./~` heuristic).
3. **Resolution** of each token against CWD using `Path.resolve()`.
4. **Relative-to check** — verifies the resolved path is inside CWD.
   Symlinks are followed, so a symlink inside CWD that points outside
   will be flagged.

### 1.5 How `check_file_path_escape()` Works

Used by `read`, `write`, `edit`, and `list_files`. It:

1. Expands `~` to the user's home directory.
2. Resolves absolute paths directly.
3. Resolves relative paths against CWD.
4. Checks `resolved.relative_to(cwd_resolved)`.
5. Returns `SecurityCheck(safe=False)` if the path is outside CWD.

---

## Layer 2 — User Confirmation

### 2.1 The Confirmation Protocol

When a security check fails, the tool returns a `ToolResult` with the
`needs_confirmation` flag set:

```python
ToolResult(
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
```

### 2.2 REPL Prompt

The REPL loop (in `src/mva/cli/repl.py`) detects `needs_confirmation`
and prompts the user:

```
Security check: Path for read is outside working directory:
  '/etc/hosts' → '/etc/hosts'
  Tool: read
  Allow this operation to proceed? [y/N]
```

- **`y` / `Y`** → re-invokes the tool with `_confirmed=True`, bypassing
  Layers 0, 1, and 2 for that invocation.
- **`n` / `N` / Enter (default)** → the operation is silently dropped.
  A message is sent back to the LLM indicating the user declined.

### 2.3 Two-Invocation Pattern

Every security-sensitive tool follows this pattern:

```python
def execute(self, command: str, _confirmed: bool = False, **kwargs):
    # First invocation — run security checks
    if not _confirmed:
        check = self.check_security(command)
        if check is not None and not check.safe:
            return _confirm_result(check, self.name, command=command)
    # Second invocation (user confirmed) — do the work
    ...
```

---

## Layer 3 — Resource Limits & Sandboxing

### 3.1 OS-Level Resource Limits

Applied via `resource.setrlimit()` as a `preexec_fn` before every bash
command:

```python
def _set_resource_limits() -> None:
    import resource
    mb = 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS,     (512 * mb, 512 * mb))   # virtual memory
    resource.setrlimit(resource.RLIMIT_CPU,    (30, 30))                # CPU seconds
    resource.setrlimit(resource.RLIMIT_FSIZE,  (50 * mb, 50 * mb))     # file write size
```

| Limit | Value | Purpose |
|---|---|---|
| `RLIMIT_AS` | 512 MB | Prevents memory-exhaustion attacks |
| `RLIMIT_CPU` | 30 seconds | Prevents runaway computations |
| `RLIMIT_FSIZE` | 50 MB | Prevents disk-filling writes |
| `RLIMIT_NPROC` | 50 (per AGENT.md) | Prevents process-fork bombs |

### 3.2 Sanitized Execution Environment

Bash commands run in a **sanitised environment**:

```python
sandbox_env = {
    "HOME": cwd,                              # HOME → CWD (not real home)
    "PATH": "/usr/bin:/bin:/usr/local/bin:/usr/sbin:/sbin",  # restricted PATH
    "PWD": cwd,
    "USER": os.environ.get("USER", "user"),
    "LANG": "C.UTF-8",
    "SHELL": "/bin/bash",
    "TERM": "dumb",                           # no terminal escape codes
}
```

### 3.3 Process Isolation

- Commands are spawned with `start_new_session=True`, creating a new
  process group.
- On timeout, the **entire process group** is killed via
  `os.killpg(os.getpgid(pid), signal.SIGKILL)` — no orphaned children.
- `subprocess.TimeoutExpired` triggers a two-stage kill (SIGKILL, then
  a 5-second grace period for zombie reaping).

### 3.4 Output Sanitisation

All output is scrubbed before being returned to the LLM:

```python
def _sanitize_output(text: str) -> str:
    """Strip ANSI escapes and control characters (keep \\t, \\n, \\r)."""
    ansi_re = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    text = ansi_re.sub("", text)
    return "".join(c for c in text if ord(c) >= 0x20 or c in "\t\n\r")
```

### 3.5 Output Truncation

Output is capped at **2000 lines** or **50 KB** (whichever is hit
first), keeping the **tail** (latest output). If truncated, the full
output is saved to a temp file whose path is appended to the result:

```
[Output truncated — showing last 2000 of 4500 lines (lines limit)]
[Full output saved to: /tmp/mva-bash-XXXXXX.log]
```

### 3.6 Timeout Handling

- Default timeout: **30 seconds** (configurable per invocation).
- Double-kill strategy for stubborn processes:
  1. `proc.communicate(timeout=30)` — first attempt.
  2. `killpg()` → `communicate(timeout=5)` — forced kill.
  3. `killpg()` → `communicate(timeout=5)` — retry if still alive.

---

## End-to-End Flow

```
User enters a message
       │
       ▼
LLM returns tool call → bash("cat /etc/passwd")
       │
       ▼
ToolRegistry.execute(name="bash", arguments={"command": "cat /etc/passwd"})
       │
       ├── Layer 0: Blocklist match?
       │     └─ "cat /etc/passwd" → no match → proceed
       │
       ├── Layer 1: check_security()
       │     └─ check_bash_escape("cat /etc/passwd", cwd)
       │           ├─ "/etc" in command? → YES → SecurityCheck(safe=False)
       │           └─ Return: SecurityCheck(safe=False, message="...")
       │
       ├── Layer 2: needs_confirmation=True back to REPL
       │     └─ REPL prompts: "Allow this operation? [y/N]"
       │
       ├── User: [y]
       │     └─ ToolRegistry.execute(name="bash", command=..., confirmed=True)
       │           └─ BashTool.execute(command, _confirmed=True)
       │                 │
       │                 ├── Layer 3: _set_resource_limits()
       │                 │     └─ Popen with sandboxed env
       │                 │
       │                 ├── Command runs (max 30s)
       │                 │
       │                 ├── Output sanitised & truncated
       │                 │
       │                 └── ToolResult(content="...", exit_code=0)
       │
       └── Result returned to LLM → next turn
```

---

## Per-Tool Security Implementation

### `bash` — Sandboxed Shell

| Check | Method |
|---|---|
| Blocklist | `_DANGEROUS_PATTERNS` regex match |
| Path escape | `check_bash_escape()` — string search + token extraction |
| Resource limits | `_set_resource_limits()` via `preexec_fn` |
| Timeout | `subprocess.communicate(timeout=N)` |
| Output limits | `_truncate_tail()` — 2000 lines / 50 KB |

### `read` — File Reading

```python
def check_security(self, path: str, **kwargs) -> SecurityCheck | None:
    return check_file_path_escape(path, str(Path.cwd()), operation="read")
```

### `write` — File Writing

```python
def check_security(self, path: str, **kwargs) -> SecurityCheck | None:
    return check_file_path_escape(path, str(Path.cwd()), operation="write")
```

### `edit` — File Editing

Same pattern as `read` and `write` — delegates to
`check_file_path_escape()`.

### `list_files` — Directory Listing

```python
def check_security(self, path: str, **kwargs) -> SecurityCheck | None:
    return check_file_path_escape(path, str(Path.cwd()), operation="list")
```

### `fetch_url` — HTTP Requests

No security checks — URL fetching is read-only and does not touch the
local filesystem. Output is capped at 512 KB at the transport level.

---

## Adding Security to a New Tool

Every new tool that touches the filesystem or shell **must** implement
the security contract.

### Step 1: Subclass `Tool` (class-based, preferred)

```python
from mva.agent.tools.base import Tool, ToolResult, SecurityCheck
from mva.agent.tools.path_security import check_file_path_escape
from pathlib import Path


class MyTool(Tool):
    name = "my_tool"
    description = "What this tool does"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to operate on",
            },
        },
        "required": ["path"],
    }

    def check_security(self, path: str, **kwargs) -> SecurityCheck | None:
        """Gate Layer 1: path escape detection."""
        return check_file_path_escape(path, str(Path.cwd()), operation="my_tool")

    def execute(self, path: str, _confirmed: bool = False, **kwargs) -> ToolResult:
        # Layer 2: confirmation gate
        if not _confirmed:
            check = self.check_security(path)
            if check is not None and not check.safe:
                return ToolResult(
                    content="",
                    needs_confirmation=True,
                    confirmation_message=(
                        f"Security check: {check.message}\n"
                        f"  Tool: {self.name}\n"
                        f"  Allow this operation to proceed?"
                    ),
                    confirmation_tool=self.name,
                    confirmation_args={"path": path},
                )

        # Actual implementation follows here (Layer 3 applies at runtime)
        ...
        return ToolResult(content="Done")
```

### Step 2: Register the Tool

Add to `src/mva/agent/tools/builtin/__init__.py`:

```python
from .my_tool import MyTool

def register_all(registry):
    ...
    registry.register(MyTool())
```

### Step 3: Test

Run MVA and invoke `/tools` to verify your tool appears. Try an
escape path (e.g. `/etc/passwd`) to verify the confirmation prompt
fires.

### Security Checklist for New Tools

- [ ] Does the tool touch the filesystem? → Add `check_file_path_escape()` in `check_security()`.
- [ ] Does the tool execute shell commands? → Add `check_bash_escape()` and resource limits.
- [ ] Does the tool accept `_confirmed: bool = False` in `execute()`?
- [ ] Does `check_security()` return `None` when safe, `SecurityCheck(...)` when not?
- [ ] Is the tool registered in the built-in `register_all()` or discovered via entry points?

---

## Key Source Files

| File | Purpose |
|---|---|
| `src/mva/agent/tools/base.py` | `Tool`, `ToolResult`, `SecurityCheck`, `ToolDef` base types |
| `src/mva/agent/tools/path_security.py` | `check_file_path_escape()`, `check_bash_escape()` |
| `src/mva/agent/tools/registry.py` | `ToolRegistry.execute()` — security gate, confirmation protocol |
| `src/mva/agent/tools/builtin/bash.py` | `BashTool` — blocklist, resource limits, output sanitisation |
| `src/mva/agent/tools/builtin/read.py` | `ReadTool` — read security |
| `src/mva/agent/tools/builtin/write.py` | `WriteTool` — write security |
| `src/mva/agent/tools/builtin/edit.py` | `EditTool` — edit security |
| `src/mva/agent/tools/builtin/list_files.py` | `ListFilesTool` — list security |
| `src/mva/cli/repl.py` | REPL loop — confirmation prompt handling |
| `AGENT.md` | Project-level overview of the 4-layer stack |

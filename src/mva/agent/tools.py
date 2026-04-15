"""
tools.py

Central Tool Service for the Minimally Viable Python Coding Agent.
- Simple @sandbox decorator.
- Automatic registration of built-in tools.
- Strict single-folder sandbox with clear error types.
"""

from __future__ import annotations

import json
import os
import warnings
import inspect
import importlib.util
import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..utils.log import get_logger

_log = get_logger("tools")


# ====================== Custom Exceptions ======================

class SandboxError(PermissionError):
    """Raised when any operation attempts to violate the single-folder sandbox."""
    pass


class ToolsNotSupportedError(RuntimeError):
    """Raised when the requested tool does not exist."""
    pass


# ====================== Sandbox Utilities ======================

def get_sandbox_root() -> Path:
    root_str = os.getenv("SANDBOX_DIR", "/tmp/agent_workspace")
    return Path(root_str).resolve()


def safe_path(rel: str | Path) -> Path:
    """Strict path validation - only allow inside sandbox root."""
    root = get_sandbox_root()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise SandboxError(f"Access denied: '{rel}' escapes sandbox root '{root}'")
    return target


def sandbox(fn: Callable) -> Callable:
    """Simple decorator: automatically sanitizes file path arguments.

    Only sanitizes parameters named 'filename', 'path', 'filepath', or 'dir'.
    Other string arguments (like 'code') are left untouched.

    Preserves the original function's signature so that Tool.from_function()
    can correctly extract parameter information for schema generation.
    """
    # Parameters that represent file paths (not code, content, etc.)
    PATH_PARAMS = {"filename", "path", "filepath", "dir", "directory", "file_path"}

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        sig = inspect.signature(fn)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        for name, value in list(bound.arguments.items()):
            # Only sanitize string/Path values for path-like parameters
            if isinstance(value, (str, Path)) and name.lower() in PATH_PARAMS:
                try:
                    bound.arguments[name] = safe_path(value)
                except SandboxError:
                    raise
                except Exception:
                    pass

        return fn(**bound.arguments)

    return wrapper


# ====================== Sandbox Backend ======================

class SandboxResult:
    def __init__(self, stdout: str = "", stderr: str = "", exit_code: int = -1, success: bool = False):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.success = success


class PythonSandbox:
    def __init__(self, base_workspace: Path):
        self.base_workspace = base_workspace.resolve()
        self.base_workspace.mkdir(parents=True, exist_ok=True)

    def execute(self, code: str, files: Optional[Dict[str, str]] = None, timeout: int = 30) -> SandboxResult:
        import subprocess, uuid

        session_id = str(uuid.uuid4())
        workspace_dir = self.base_workspace / session_id
        workspace_dir.mkdir(parents=True, exist_ok=True)

        if files:
            for name, content in files.items():
                (workspace_dir / name).write_text(content, encoding="utf-8")

        code_path = workspace_dir / "__agent_code__.py"
        code_path.write_text(code, encoding="utf-8")

        try:
            result = subprocess.run(
                ["python3", str(code_path)],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={"PYTHONPATH": str(workspace_dir), "HOME": str(workspace_dir), "PATH": "/usr/bin:/bin"},
                preexec_fn=self._preexec(workspace_dir),
            )
            return SandboxResult(
                stdout=result.stdout, stderr=result.stderr,
                exit_code=result.returncode, success=result.returncode == 0
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(stderr="Execution timed out", success=False)
        except Exception as e:
            return SandboxResult(stderr=str(e), success=False)

    def _preexec(self, workspace_dir: Path):
        def setup():
            os.chdir(workspace_dir)
            if os.geteuid() == 0:
                os.setgid(65534)
                os.setuid(65534)
        return setup

    def read_file(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_file(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def list_files(self, path: Path) -> list[str]:
        return [p.name for p in path.iterdir() if not p.name.startswith('.')]


# ====================== Tool Definition ======================

_PY_TO_JSON_TYPE = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object", list: "array"}


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})

    @classmethod
    def from_function(cls, fn: Callable, description: str | None = None) -> "Tool":
        sig = inspect.signature(fn)
        hints = getattr(fn, "__annotations__", {})
        props = {}
        required = []

        for name, param in sig.parameters.items():
            ann = hints.get(name, str)
            props[name] = {"type": _PY_TO_JSON_TYPE.get(ann, "string")}
            if param.default is inspect.Parameter.empty:
                required.append(name)

        return cls(
            name=fn.__name__,
            description=description or inspect.getdoc(fn) or f"Tool: {fn.__name__}",
            fn=fn,
            parameters={"type": "object", "properties": props, "required": required},
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def __call__(self, **kwargs):
        return self.fn(**kwargs)


# ====================== Global Service ======================

_sandbox: PythonSandbox # required
_loaded_tools: List[Tool] = []


def init_sandbox(workspace_root: Optional[Path] = None) -> None:
    """Initialize the sandbox service."""
    global _sandbox
    if workspace_root:
        os.environ["SANDBOX_DIR"] = str(workspace_root.resolve())
    
    root = get_sandbox_root()
    root.mkdir(parents=True, exist_ok=True)
    _sandbox = PythonSandbox(base_workspace=root)


def get_available_tools() -> List[dict]:
    """Return tool schemas for the LLM."""
    return [tool.schema() for tool in _loaded_tools]


def normalize_arguments(arguments: Any) -> Dict[str, Any]:
    """Normalize various ways LLMs pass arguments.

    Handles:
    - String JSON parsing
    - Single-key unwrapping: {"args": {...}} → {...}
    - Direct dict pass-through
    """
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            # After parsing, check if it's a single-key wrapper
            if isinstance(parsed, dict):
                if "args" in parsed and len(parsed) == 1:
                    return parsed["args"]
                if "arguments" in parsed and len(parsed) == 1:
                    return parsed["arguments"]
            return parsed
        except:
            return {}

    if isinstance(arguments, dict):
        # Check for single-key wrappers and unwrap once
        if "args" in arguments and len(arguments) == 1 and isinstance(arguments["args"], dict):
            return arguments["args"]
        if "arguments" in arguments and len(arguments) == 1 and isinstance(arguments["arguments"], dict):
            return arguments["arguments"]
        return arguments

    return {}

def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Central entrypoint for all tool execution.

    Arguments are normalized once via normalize_arguments() to handle
    common wrapping patterns from LLMs before being passed to the tool.
    """
    global _sandbox
    if _sandbox is None:
        init_sandbox()

    _log.debug("execute_tool: %s (raw args: %s)", tool_name, arguments)

    # Normalize arguments once (handles JSON parsing and unwrapping)
    arguments = normalize_arguments(arguments)
    _log.debug("execute_tool: %s (normalized args: %s)", tool_name, arguments)

    for tool in _loaded_tools:
        if tool.name == tool_name:
            try:
                _log.info("tool_call: %s with args %s", tool_name, arguments)
                result = tool(**arguments)
                _log.debug("tool_result: %s returned %s", tool_name, result)
                return {"success": True, "result": result}
            except TypeError as e:
                if "unexpected keyword argument" in str(e):
                    error_msg = f"Tool '{tool_name}' received unexpected arguments: {arguments}"
                    _log.warning("tool_error: %s — %s", tool_name, error_msg)
                    return {"success": False, "error": error_msg}
                _log.warning("tool_error: %s — %s", tool_name, e)
                return {"success": False, "error": str(e)}
            except SandboxError as e:
                _log.warning("tool_sandbox_violation: %s — %s", tool_name, e)
                return {"success": False, "error": str(e)}
            except Exception as e:
                _log.error("tool_execution_failed: %s — %s", tool_name, e, exc_info=True)
                return {"success": False, "error": f"Tool execution failed: {e}"}

    _log.error("tool_not_found: %s (available: %s)", tool_name, [t.name for t in _loaded_tools])
    raise ToolsNotSupportedError(f"Tool '{tool_name}' is not supported.")

# ====================== Built-in Tools with @sandbox ======================

@sandbox
def read_file(filename: str) -> str:
    """
    Read a file from the sandbox workspace (single folder only).
    Args:
    - filename: The name of the file to read (relative to sandbox root).
    Returns:
    - The content of the file as a string.
    Raises:
    - SandboxError: If the filename attempts to escape the sandbox.
    - FileNotFoundError: If the file does not exist.
    - IOError: If there is an error reading the file.
    """
    return _sandbox.read_file(safe_path(filename))


@sandbox
def write_file(filename: str, content: str) -> str:
    """
    Write content to a file in the sandbox workspace.
    If the file already exists, it will be overwritten.
    
    Args:
    - filename: The name of the file to write (relative to sandbox root).
    - content: The string content to write to the file.
    Returns:
    - A success message indicating the file was written.
    Raises:
    - SandboxError: If the filename attempts to escape the sandbox.
    - IOError: If there is an error writing the file.
    """
    _sandbox.write_file(safe_path(filename), content)
    return f"Successfully wrote to file: {filename}"


@sandbox
def list_files(path: Path = Path(".")) -> list[str]:
    """
    List files in the sandbox workspace.
    
    Args:
        path: The path to list files in. If None, uses the base workspace.
    Returns:
        A list of filenames.
    """
    if path is None:
        path = _sandbox.base_workspace
    return _sandbox.list_files(path)


@sandbox
def code_execution(code: str, files: Optional[Dict[str, str]] = None, timeout: int = 30) -> dict:
    """
    Execute Python code inside the strict single-folder sandbox.

    Args:
        code: The Python code to execute.
        files: Optional dict of filename → content to create before execution.
        timeout: Maximum execution time in seconds.
    Returns:
        A dict with keys: success (bool), stdout (str), stderr (str), exit_code (int).
    """
    if not isinstance(code, str):
        code = str(code)                    # extra safety

    result: SandboxResult = _sandbox.execute(code, files or {}, timeout=timeout)
    return {
        "success": result.success,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
    }

# ====================== Automatic Tool Registration ======================

def _register_built_in_tools() -> None:
    """Automatically register all built-in tools when the module is imported."""
    global _loaded_tools
    built_ins = [read_file, write_file, list_files, code_execution]
    for fn in built_ins:
        _loaded_tools.append(Tool.from_function(fn))


# Auto-register built-in tools on module import
_register_built_in_tools()
_log.debug("Registered %d built-in tools", len(_loaded_tools))


# ====================== Tool Loader for Custom Tools ======================

def _load_fns_from_file(py_file: Path) -> list[Callable]:
    spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        warnings.warn(f"Could not load tool file {py_file}: {exc}")
        return []

    names = getattr(mod, "__all__", None) or [
        n for n in dir(mod)
        if not n.startswith("_")
        and callable(getattr(mod, n))
        and getattr(getattr(mod, n), "__doc__", None)
    ]
    return [getattr(mod, n) for n in names if callable(getattr(mod, n))]


def load_tools_from_directory(tool_dir: Path = Path("tools")) -> None:
    """Load custom tools from a directory (optional).

    Skips duplicate tool names to prevent re-registration.
    """
    global _loaded_tools
    tool_dir = Path(tool_dir)
    _log.debug("load_tools_from_directory: scanning %s", tool_dir)

    py_files = list(tool_dir.glob("*.py"))
    if not py_files:
        _log.debug("load_tools_from_directory: no .py files found in %s", tool_dir)
        return

    # Track existing tool names to prevent duplicates
    existing_names = {t.name for t in _loaded_tools}

    tools_added = 0
    for py_file in py_files:
        if py_file.name.startswith("_"):
            continue
        fns = _load_fns_from_file(py_file)
        for fn in fns:
            tool = Tool.from_function(fn)
            # Only register if not already loaded
            if tool.name not in existing_names:
                _loaded_tools.append(tool)
                existing_names.add(tool.name)
                tools_added += 1
                _log.debug("load_tools_from_directory: registered tool '%s' from %s", tool.name, py_file.name)
            else:
                _log.debug("load_tools_from_directory: skipped duplicate tool '%s' from %s", tool.name, py_file.name)

    _log.info("load_tools_from_directory: loaded %d tool(s) from %s", tools_added, tool_dir)


def register_tool(fn: Callable, description: str | None = None) -> None:
    """Manually register additional tools."""
    tool = Tool.from_function(fn, description)
    _loaded_tools.append(tool)
    _log.debug("register_tool: registered '%s'", tool.name)
# How to Add Tools to MVA

This document outlines the process for extending the MVA (Model-based Virtual Agent) repository with new capabilities via tool definitions.

## Overview

MVA uses a decorator-based registry system located in `src/mva/tools/__init__.py`. This system allows the LLM to discover tool definitions (names, descriptions, and parameters) and provides a unified way to execute them.

## The Tool Pattern

Every tool must consist of two parts:
1.  **A `ToolDef`**: Metadata defining the tool's interface for the LLM.
2.  **An Executor Function**: The Python logic that performs the action.

## Implementation Steps

### 1. Define and Register the Tool
Use the `@_register` decorator. This automatically adds the tool to the global registry.

```python
@_register(
    name="tool_name",
    description="A clear description of what this tool does for the LLM.",
    parameters={
        "type": "object",
        "properties": {
            "arg_name": {"type": "string", "description": "Description of the argument."},
        },
        "required": ["arg_name"],
    },
)
def tool_function_name(arg_name: str, _confirmed: bool = False) -> ToolResult:
    # Implementation logic
    ...
```

### 2. Implement the Logic
Your function must return a `ToolResult` object.

*   **Success**: `return ToolResult(content="Success message")`
*   **Failure**: `return ToolResult(content="Error message", is_error=True)`

### 3. Security and Confirmation (Mandatory for System Tools)
If your tool interacts with the file system, network, or shell, you must implement the security stack used by existing tools:

1.  **Include `_confirmed`**: Always include `_confirmed: bool = False` in your function signature.
2.  **Perform Escape Checks**: If your tool accepts paths, use `check_file_path_escape` from `mva.tools.path_security`.
3.  **Handle User Approval**: If a security check fails, return a `ToolResult` that triggers the REPL's confirmation prompt:

```python
if not _confirmed:
    check = check_file_path_escape(path, str(Path.cwd()), operation="my_op")
    if not check.safe:
        return _confirm_request(check, "tool_name", path=path, ...)
```

## Summary of `ToolResult`
The `ToolResult` class is used to communicate the outcome back to the agent:
*   `content` (str): The text to be sent back to the LLM.
*   `is_error` (bool): Whether the operation failed.
*   `needs_confirmation` (bool): Whether the user needs to approve a sensitive action.
*   `confirmation_message` (str): The message shown to the user during a security check.

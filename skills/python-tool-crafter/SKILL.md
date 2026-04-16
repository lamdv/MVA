---
name: python-tool-crafter
description: Write sandbox-safe Python tools for the MVA agent
---

# Python Tool Crafter Skill

Use this skill when you need to generate a new Python tool for the agent.

## Step 1: Understand the Context

Tools are Python functions decorated with `@sandbox` that:
- Are sandboxed to a single folder (no file escapes)
- Use only Python standard library (no external dependencies)
- Have clear docstrings describing what they do
- Accept typed parameters for schema generation
- Return simple, JSON-serializable results

## Step 2: Design the Tool

Identify:
1. **Purpose**: What problem does this tool solve?
2. **Inputs**: What parameters does it need? (type hints required)
3. **Output**: What does it return? (keep it simple)
4. **Scope**: Does it need file access? Network? Computation?

## Step 3: Write the Function

Template:

```python
from pathlib import Path

@sandbox
def tool_name(param1: str, param2: int = 10) -> dict:
    """
    One-line summary of what this tool does.
    
    Use when you need to: [specific problem]
    
    Args:
        param1: Description of first parameter
        param2: Description of second parameter (default: 10)
    
    Returns:
        A dict with keys explaining the result structure
    
    Raises:
        ValueError: If parameters are invalid
    """
    # Implementation using stdlib only
    result = {}
    return result
```

## Step 4: Implementation Rules

### ✅ DO:
- Use only Python standard library (json, os, re, pathlib, etc)
- Type-hint all parameters
- Type-hint the return value
- Include detailed docstring
- Return dicts or simple types (str, int, list, dict)
- Use `@sandbox` decorator if tool touches files
- Handle errors gracefully

### ❌ DON'T:
- Import external packages (requests, pandas, etc) unless explicitly allowed
- Use hardcoded paths
- Write to locations outside sandbox
- Assume any Python modules exist
- Return objects that can't be JSON-serialized
- Skip docstrings
- Ignore type hints

## Step 5: Sandbox Decorator Behavior

The `@sandbox` decorator:
- Sanitizes path-like parameters (filename, path, filepath, dir, directory, file_path)
- Blocks attempts to escape the sandbox root
- Leaves code content untouched (code execution tools handle that)

If your tool has file parameters, use descriptive names:
```python
@sandbox
def process_file(filename: str, format: str) -> dict:
    """Process a file in the workspace."""
    from pathlib import Path
    path = Path(filename)  # Automatically sandboxed
    # ...
```

## Step 6: Common Patterns

### Pattern: Read & Process
```python
@sandbox
def analyze_code(filename: str) -> dict:
    """Analyze Python code in a file."""
    import ast
    with open(filename) as f:
        tree = ast.parse(f.read())
    return {"functions": len([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)])}
```

### Pattern: Compute & Return
```python
def calculate_metrics(data_str: str) -> dict:
    """Calculate statistics from comma-separated numbers."""
    import statistics
    numbers = [float(x.strip()) for x in data_str.split(",")]
    return {
        "mean": statistics.mean(numbers),
        "median": statistics.median(numbers),
        "count": len(numbers)
    }
```

### Pattern: Transform & Write
```python
@sandbox
def transform_file(filename: str, operation: str) -> dict:
    """Transform file content (uppercase, reverse, etc)."""
    import json
    with open(filename) as f:
        content = f.read()
    
    if operation == "uppercase":
        result = content.upper()
    elif operation == "reverse":
        result = content[::-1]
    else:
        raise ValueError(f"Unknown operation: {operation}")
    
    # Write back
    with open(filename, "w") as f:
        f.write(result)
    
    return {"success": True, "operation": operation}
```

## Step 7: Validation

Before submitting, verify:
- [ ] Has `@sandbox` decorator if touching files
- [ ] All parameters have type hints
- [ ] Return type is specified
- [ ] Docstring explains purpose and parameters
- [ ] Uses only stdlib (json, pathlib, re, os, etc)
- [ ] Error cases handled
- [ ] Returns JSON-serializable result

## Example: HTTP Fetch Tool

Here's a complete example of a tool you might generate:

```python
@sandbox
def fetch_url(url: str, timeout: int = 10) -> dict:
    """
    Fetch content from an HTTP URL using stdlib.
    
    Use when you need to: Get data from a web API or download a file
    
    Args:
        url: The HTTP(S) URL to fetch
        timeout: Request timeout in seconds (default: 10)
    
    Returns:
        dict with keys:
        - success: bool
        - status_code: int (if successful)
        - content: str (response body if successful)
        - error: str (if failed)
    """
    import urllib.request
    import urllib.error
    
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            content = response.read().decode('utf-8')
            return {
                "success": True,
                "status_code": response.status,
                "content": content[:10000]  # Limit size
            }
    except urllib.error.URLError as e:
        return {
            "success": False,
            "error": f"URL error: {e.reason}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }
```

## When NOT to Generate a Tool

Don't generate a tool if:
- It requires external packages
- It's a one-time operation the agent can do directly
- It duplicates existing tools (read_file, write_file, code_execution, list_files)
- It needs network access beyond stdlib
- It needs privileged system access

---

**Use this skill when Phase 3 (Improve) needs to generate a missing tool based on telemetry insights.**

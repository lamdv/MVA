# Tools System

Tools are low-level, auto-discoverable functions that the agent can call to accomplish tasks. They form the foundation for agent capabilities.

## Quick Start

Create a tool:

```python
# tools/greet.py
@sandbox
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"

# Auto-discovered and immediately available to the agent!
```

Use it:

```bash
$ uv run mva chat
You: Greet Alice
🔧 Calling greet...
Hello, Alice!
```

---

## Creating Tools

### Basic Tool

```python
# tools/math_tools.py

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b
```

**Requirements:**
- Function must have a docstring
- Parameters must have type hints
- File must be in `tools_dir` (default: `./tools/`)
- Name starts with lowercase (public functions only)

**Result:** Auto-registered as tools with:
- Name: `add`, `multiply`
- Description: Docstring first line
- Parameters: Extracted from function signature

### Tool with Sandboxing

```python
# tools/file_operations.py
from mva.agent.tools import sandbox
from pathlib import Path

@sandbox
def read_file(filename: str) -> str:
    """Read a file from the sandbox workspace."""
    return Path(filename).read_text()

@sandbox  
def write_file(filename: str, content: str) -> str:
    """Write content to a file in the sandbox workspace."""
    Path(filename).write_text(content)
    return f"Wrote {len(content)} bytes to {filename}"

@sandbox
def list_files(path: str = ".") -> list[str]:
    """List files in a directory."""
    return [f.name for f in Path(path).iterdir()]
```

**How `@sandbox` works:**
- Inspects function signature
- For path-like parameters (`filename`, `path`, `dir`, etc.):
  - Calls `safe_path()` to validate against sandbox root
  - Prevents path escapes (e.g., `../../etc/passwd`)
  - Raises `SandboxError` on violation
- Other string parameters (`code`, `content`) are left untouched
- Applies parameter defaults before validation

### Tool with Optional Parameters

```python
# tools/search.py

def search_docs(query: str, max_results: int = 10) -> list[str]:
    """Search documentation files.
    
    Args:
        query: The search query
        max_results: Maximum number of results (default: 10)
    
    Returns:
        List of matching file paths
    """
    # Implementation
    return results
```

**How it works:**
- `query` is required (no default)
- `max_results` is optional (has default)
- Appears in tool schema as required/optional

---

## Tool Discovery

### Automatic Discovery

Tools are auto-discovered from `tools_dir`:

```
tools/
├── math.py          # Loaded
├── file_ops.py      # Loaded
├── _internal.py     # Skipped (starts with _)
└── helpers/         # Skipped (not .py file)
```

**Discovery rules:**
1. Scan `tools_dir` for `.py` files
2. Skip files starting with `_`
3. For each file, find all public callables with docstrings
4. Register as `Tool` objects

### Manual Discovery

```python
from mva.agent.tools import load_tools_from_directory
from pathlib import Path

# Load tools on demand
load_tools_from_directory(Path("./my_tools"))
```

### Manual Registration

```python
from mva.agent.tools import register_tool

def custom_tool(x: int) -> int:
    """Double a number."""
    return x * 2

register_tool(custom_tool)
```

Or with custom description:

```python
register_tool(custom_tool, description="Double any integer")
```

---

## Tool Schema

Tools are automatically converted to OpenAI-compatible schemas for the LLM:

```python
def read_file(filename: str) -> str:
    """Read a file from the sandbox workspace."""
    ...
```

Becomes:

```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read a file from the sandbox workspace.",
    "parameters": {
      "type": "object",
      "properties": {
        "filename": {"type": "string"}
      },
      "required": ["filename"]
    }
  }
}
```

**Type mapping:**
- `str` → `"string"`
- `int` → `"integer"`
- `float` → `"number"`
- `bool` → `"boolean"`
- `dict` → `"object"`
- `list` → `"array"`
- Unknown → `"string"` (default)

---

## Argument Handling

### Normal Arguments

```python
def read_file(filename: str) -> str:
    ...

# Called as: read_file("data.txt")
```

### Optional Arguments

```python
def search(query: str, limit: int = 10) -> list:
    ...

# Can be called as:
# search("python")           # Uses default limit=10
# search("python", 100)      # Custom limit
```

### Argument Normalization

The agent's arguments are normalized before being passed to tools:

**Input:**
```json
{"filename": "test.txt"}
```

**Normalized:**
```python
# Handles these cases:
{
  "filename": "test.txt"      # Direct pass-through
}
```

**Unwrapping:**
```json
{"args": {"filename": "test.txt"}}     // Unwrapped
{"arguments": {"filename": "test.txt"}}  // Unwrapped
```

This allows tools to work with different LLM APIs transparently.

---

## Sandbox System

### Purpose

Prevent file operations from escaping a designated workspace directory.

```
Allowed:
✓ ./workspace/data.txt
✓ ./workspace/subdir/file.txt
✓ /tmp/agent_workspace/output.txt

Rejected:
✗ /etc/passwd               (absolute path outside sandbox)
✗ ../../sensitive_file.txt (relative escape)
✗ /home/user/private.txt   (outside workspace)
```

### Configuration

Set sandbox root:

```python
from mva.agent.tools import init_sandbox
from pathlib import Path

init_sandbox(Path("/custom/workspace"))
```

Or via environment:

```bash
export SANDBOX_DIR=/tmp/mva_workspace
```

### How It Works

```python
@sandbox
def read_file(filename: str) -> str:
    # Input: "data.txt"
    # In decorator: safe_path("data.txt")
    #   → Resolves to: /tmp/agent_workspace/data.txt
    #   → Checks: is within /tmp/agent_workspace? Yes ✓
    #   → Returns: Path object
    # Function receives: Path object (not string)
    return Path(filename).read_text()
```

### Escape Detection

```python
# safe_path() logic:
root = Path("/tmp/agent_workspace")
target = (root / "../../etc/passwd").resolve()

try:
    target.relative_to(root)  # Does it stay within root?
except ValueError:
    raise SandboxError(f"Access denied: escapes sandbox")
```

### Path Parameter Detection

The `@sandbox` decorator only sanitizes path-like parameters:

```python
@sandbox
def process(
    filename: str,        # ← Sanitized
    content: str,         # ← NOT sanitized
    directory: str,       # ← Sanitized
    code: str            # ← NOT sanitized
) -> str:
    ...
```

**Path-like names:** `filename`, `path`, `filepath`, `dir`, `directory`, `file_path`

Any other name is left as-is (allows tools to receive code, text, etc. without modification).

---

## Error Handling

### SandboxError

Raised when a path escapes the sandbox:

```python
@sandbox
def read_file(filename: str) -> str:
    # If filename = "../../etc/passwd"
    # Raises: SandboxError("Access denied: '../../etc/passwd' escapes sandbox root...")
    ...
```

The LLM receives this error and can:
- Ask for clarification
- Suggest an alternative
- Explain the limitation

### ToolsNotSupportedError

Raised when the agent calls a tool that doesn't exist:

```python
# Agent tries to call: undefined_tool()
# Result: ToolsNotSupportedError("Tool 'undefined_tool' is not supported")
# Available: ['read_file', 'write_file', ...]
```

### TypeError

Raised when arguments don't match the function signature:

```python
def add(a: int, b: int) -> int:
    return a + b

# If agent calls: add(a=5)  # Missing 'b'
# Result: TypeError("add() missing required argument: 'b'")
```

### Generic Exceptions

Any other exception during tool execution:

```python
def buggy_tool() -> str:
    return 1 / 0  # ZeroDivisionError

# Result: {"success": false, "error": "division by zero"}
# LLM informed of failure and can respond appropriately
```

---

## Built-in Tools

MVA provides four built-in tools:

### read_file(filename: str) → str

Read a file from the sandbox workspace.

```python
read_file("data.txt")
# Returns: file contents as string

read_file("subdir/config.json")
# Returns: JSON content
```

### write_file(filename: str, content: str) → str

Write content to a file in the sandbox workspace.

```python
write_file("output.txt", "Hello, world!")
# Returns: "Successfully wrote to file: output.txt"

write_file("data.json", json.dumps({"key": "value"}))
```

### list_files(path: str = ".") → list[str]

List files in a directory.

```python
list_files()           # Lists current directory
list_files("data")     # Lists data/ subdirectory
list_files("/")        # Lists sandbox root
# Returns: ["file1.txt", "file2.py", ...]
```

### code_execution(code: str, files: dict = None, timeout: int = 30) → dict

Execute Python code in the sandbox.

```python
result = code_execution("print(2 + 2)")
# Returns: {
#   "success": true,
#   "stdout": "4\n",
#   "stderr": "",
#   "exit_code": 0
# }

# With files
code = """
import json
with open('input.json') as f:
    data = json.load(f)
print(len(data))
"""
result = code_execution(code, files={"input.json": '{"a": 1}'})
```

---

## Best Practices

### 1. Clear Docstrings

❌ **Bad:**
```python
def process(x):
    """Process x."""
    ...
```

✅ **Good:**
```python
def process_data(filename: str, format: str = "json") -> dict:
    """Process data from a file.
    
    Args:
        filename: Path to the data file (relative to workspace)
        format: File format (json, csv, or txt)
    
    Returns:
        Parsed data as a dictionary
    """
    ...
```

### 2. Type Hints

❌ **Bad:**
```python
def add(a, b):
    """Add two numbers."""
    return a + b
```

✅ **Good:**
```python
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
```

### 3. Specific, Focused Tools

❌ **Bad:**
```python
def file_operation(op: str, filename: str, content: str = None):
    """Do file operations."""
    if op == "read":
        return Path(filename).read_text()
    elif op == "write":
        Path(filename).write_text(content)
    # ... too broad
```

✅ **Good:**
```python
@sandbox
def read_file(filename: str) -> str:
    """Read a file from the sandbox workspace."""
    return Path(filename).read_text()

@sandbox
def write_file(filename: str, content: str) -> str:
    """Write content to a file in the sandbox workspace."""
    Path(filename).write_text(content)
    return f"Wrote to {filename}"
```

### 4. Error Messages

❌ **Bad:**
```python
def fetch(url: str) -> str:
    try:
        return requests.get(url).text
    except:
        return "error"
```

✅ **Good:**
```python
def fetch(url: str) -> str:
    """Fetch content from a URL."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.Timeout:
        raise TimeoutError(f"Request timed out: {url}")
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}")
```

### 5. Sandbox Compliance

✅ **Good:**
```python
@sandbox
def analyze_file(filename: str) -> dict:
    """Analyze a file."""
    path = Path(filename)  # Already sandboxed
    return {"size": path.stat().st_size}
```

❌ **Bad:**
```python
def analyze_file(filename: str) -> dict:
    """Analyze a file."""
    # No sandboxing - could access /etc/passwd!
    path = Path(filename)
    return {"size": path.stat().st_size}
```

---

## Examples

### Example 1: Data Processing Tools

```python
# tools/data_tools.py
import json
from pathlib import Path
from mva.agent.tools import sandbox

@sandbox
def load_json(filename: str) -> dict:
    """Load JSON from a file."""
    with open(filename) as f:
        return json.load(f)

@sandbox
def save_json(filename: str, data: dict) -> str:
    """Save data as JSON to a file."""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    return f"Saved {len(data)} items to {filename}"

def filter_data(data: list, key: str, value: str) -> list:
    """Filter a list of items."""
    return [item for item in data if item.get(key) == value]
```

### Example 2: API Tools

```python
# tools/api_tools.py
import requests

def get_json(url: str) -> dict:
    """Fetch JSON from a URL."""
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def post_json(url: str, data: dict, token: str = "") -> dict:
    """POST JSON data to a URL."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.post(url, json=data, headers=headers)
    response.raise_for_status()
    return response.json()
```

### Example 3: Text Tools

```python
# tools/text_tools.py

def extract_emails(text: str) -> list[str]:
    """Extract email addresses from text."""
    import re
    pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    return re.findall(pattern, text)

def summarize_text(text: str, max_sentences: int = 3) -> str:
    """Summarize text to N sentences."""
    sentences = text.split('. ')
    summary = '. '.join(sentences[:max_sentences])
    return summary.rstrip('. ') + '.'

def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())
```

---

## Logging

Tools log their execution:

```
DEBUG    private_notebook.tools: execute_tool: read_file (raw args: {'filename': 'test.txt'})
DEBUG    private_notebook.tools: execute_tool: read_file (normalized args: {'filename': 'test.txt'})
INFO     private_notebook.tools: tool_call: read_file with args {'filename': 'test.txt'}
DEBUG    private_notebook.tools: tool_result: read_file returned 'file content...'
```

Set `log_level: DEBUG` in config.yml to see all details.

---

## See Also

- [AGENT.md](AGENT.md) — Tool integration in Agent
- [SKILLS.md](SKILLS.md) — High-level workflows
- [ARCHITECTURE.md](ARCHITECTURE.md) — System design
- [CONFIGURATION.md](CONFIGURATION.md) — Configure tools_dir

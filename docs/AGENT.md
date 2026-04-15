# Agent System

The `Agent` class is the core of MVA — it orchestrates LLM communication, tool calling, and skill management.

## Quick Start

```python
from mva.agent import get_agent

# Create agent with auto-discovery
agent = get_agent()

# Chat (with tool loop)
history = [{"role": "user", "content": "What's 2+2?"}]
response = agent.run(history)
print(response)
```

---

## Agent Class

### Initialization

```python
from mva.agent import Agent
from mva.utils.llm_client import get_client

agent = Agent(
    client=get_client(),
    system_prompt="You are a helpful assistant.",
    model="claude-3-5-sonnet-20241022",
    temperature=0.7,
    max_tokens=2048,
    workspace_dir="/tmp/agent_workspace",
    tools_dir="./tools",
    skills_dir="./sandbox/engine/skills/",
    max_iterations=50,
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client` | BaseLLMClient | `get_client()` | LLM client (OpenAI-compatible or Anthropic) |
| `system_prompt` | str | None | System prompt for the LLM |
| `model` | str | From client | Model ID to use |
| `temperature` | float | 0.7 | Sampling temperature (0-1) |
| `max_tokens` | int | None | Max response tokens |
| `workspace_dir` | Path | `/tmp/agent_workspace` | Sandbox root for tools |
| `tools_dir` | Path | None | Directory with custom tools |
| `skills_dir` | Path | None | Directory with skill definitions |
| `max_iterations` | int | 50 | Max tool-call loop iterations |

---

## API Methods

### `run()` — Non-Streaming Tool Loop

Execute a tool-calling loop and return the final response.

```python
history = [
    {"role": "user", "content": "Write and run a Python script"}
]
response = agent.run(history)
print(response)  # Full text response
```

**Returns:** `str` — The final assistant response

**Raises:** `LLMError` if the LLM server fails

---

### `stream()` — Streaming Tool Loop

Stream responses chunk-by-chunk with real-time tool execution.

```python
history = [{"role": "user", "content": "Hello!"}]

for chunk in agent.stream(history):
    if chunk["type"] == "content":
        print(chunk["content"], end="", flush=True)
    elif chunk["type"] == "tool_start":
        print(f"\n🔧 Calling {chunk['name']}...")
    elif chunk["type"] == "tool_use":
        print(f"✓ {chunk['name']}: {chunk['result']}")
    elif chunk["type"] == "error":
        print(f"\n❌ {chunk['content']}")
```

**Yields:** Dict with keys:

| Type | Keys | Description |
|------|------|-------------|
| `content` | `type`, `content` | Text chunk |
| `reasoning` | `type`, `content` | Internal reasoning (if model supports) |
| `tool_start` | `type`, `name`, `args` | Tool execution starting |
| `tool_use` | `type`, `name`, `result` | Tool completed with result |
| `error` | `type`, `content` | Error message |

---

### `complete()` — Non-Streaming Text Only

Get just the text response without tool calling.

```python
messages = [
    {"role": "system", "content": "You are a poet"},
    {"role": "user", "content": "Write a haiku about Python"}
]
poem = agent.complete(messages)
print(poem)
```

**Returns:** `str` — Full response text

**Note:** Tool schemas are not sent, so no tool calls will occur.

---

## History Format

Messages follow OpenAI format:

```python
history = [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi there!"},
    {"role": "user", "content": "What's your name?"}
]
```

**Message Types:**

| Role | Content | Example |
|------|---------|---------|
| `system` | System prompt text | `"You are an expert Python programmer"` |
| `user` | User message | `"Write a function that..."` |
| `assistant` | Assistant response | `"Here's the function:"` |
| `tool` | Tool result | `"File successfully written"` |

The agent automatically appends `assistant` and `tool` messages during conversation.

---

## Tool Management

### Auto-Discovery

Tools are auto-discovered from `tools_dir`:

```python
# tools/math.py
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

# Automatically registered as a tool
```

### Manual Registration

```python
from mva.agent import sandbox

@sandbox  # Sandboxes file path arguments
def custom_tool(filename: str) -> str:
    """My custom tool."""
    return filename

agent = get_agent()
from mva.agent.tools import register_tool
register_tool(custom_tool)
```

### Sandbox Protection

The `@sandbox` decorator restricts file operations to `workspace_dir`:

```python
@sandbox
def read_config(filename: str):
    """Read a config file."""
    # filename: "config.yml" → /tmp/agent_workspace/config.yml
    # filename: "../../etc/passwd" → SandboxError!
    return Path(filename).read_text()
```

---

## Skill Management

### Skill Catalog

Skills are discovered from `SKILL.md` files in `skills_dir`:

```
sandbox/engine/skills/
├── web-scraping/
│   └── SKILL.md
└── data-analysis/
    └── SKILL.md
```

Each `SKILL.md` must have YAML frontmatter:

```yaml
---
name: web-scraping
description: Extract and parse data from websites
---

# Web Scraping Skill

## Step 1: Identify Target
...
```

### Skill Injection

Skills are automatically injected into the system prompt:

```
## Available Skills
Skills are high-level workflows...

- **web-scraping**: Extract and parse data from websites
- **data-analysis**: Perform exploratory data analysis

**How to use skills:**
1. Call `load_skill(name)` to read the full skill instructions
2. Follow the step-by-step workflow...
```

### Load Skill Tool

The agent automatically registers a `load_skill` tool:

```python
# Available as a tool for the LLM
def load_skill(name: str) -> str:
    """Load full instructions for a skill by name."""
    # Returns the full SKILL.md content
```

---

## Configuration

### Via config.yml

```yaml
# System prompt
system_prompt: |
  You are an expert Python Coding Agent...

# Directories
tools_dir: ./tools
skills_dir: ./sandbox/engine/skills/
soul_file: ./kb/soul.md

# LLM settings
log_level: INFO
log_file: notebook.log
```

### Via get_agent() Factory

```python
from mva.agent import get_agent

agent = get_agent(
    system_prompt="Custom prompt",
    model="claude-3-5-sonnet-20241022",
    tools_dir="./custom_tools",
    skills_dir="./custom_skills",
)
```

**Override order:**
1. Function arguments (highest priority)
2. config.yml values
3. Defaults (lowest priority)

---

## Factory Function: get_agent()

Convenience factory that auto-discovers config and resources.

```python
from mva.agent import get_agent

agent = get_agent(
    system_prompt="Optional override",
    model="Optional override",
    tools_dir="Optional override",
    skills_dir="Optional override",
)
```

### Discovery Logic

**tools_dir:**
1. Argument `tools_dir` if provided
2. `tools_dir` from config.yml
3. `./tools/` (local)
4. `~/.config/private-notebook/tools/` (user)

**skills_dir:**
1. Argument `skills_dir` if provided
2. `skills_dir` from config.yml
3. `./sandbox/engine/skills/` (local)
4. `~/.config/private-notebook/skills/` (user)

**soul_file:**
Loaded from config.yml and prepended to system prompt if found.

---

## Tool Calling Loop

### Streaming Example

```python
history = [{"role": "user", "content": "Read data.csv and summarize it"}]

for chunk in agent.stream(history):
    match chunk["type"]:
        case "content":
            print(chunk["content"], end="", flush=True)
        
        case "tool_start":
            # Tool about to be called
            print(f"\n🔧 {chunk['name']}({chunk['args']})")
        
        case "tool_use":
            # Tool result received
            print(f"✓ Result: {chunk['result'][:100]}...")
        
        case "error":
            print(f"❌ {chunk['content']}")
```

### Non-Streaming Example

```python
history = [{"role": "user", "content": "Calculate 2+2"}]
response = agent.run(history)
print(response)
# Output: The result of 2+2 is 4
```

---

## Error Handling

### LLM Errors

```python
from mva.utils.llm_client import LLMError

try:
    response = agent.run(history)
except LLMError as e:
    print(f"API error {e.status_code}: {e}")
```

### Tool Errors

Tool errors are caught and returned to the LLM for recovery:

```
Tool 'read_file' failed: SandboxError: Access denied...
```

The LLM receives this as context and can:
- Try a different tool
- Explain what went wrong
- Request user input

### Max Iterations

If the agent loops for `max_iterations` without reaching a conclusion:

```
[max_iterations reached]
```

Adjust with:

```python
agent = Agent(..., max_iterations=100)
```

---

## Performance Tips

### Temperature & Sampling

```python
# For deterministic, focused responses
agent = Agent(..., temperature=0.1)

# For creative, varied responses
agent = Agent(..., temperature=0.9)
```

### Token Limits

```python
# Limit response length
agent = Agent(..., max_tokens=1000)
```

### Tool Selection

Fewer, more specific tools = faster, more accurate calling:

```python
# Good: specific tools
tools/
├── read_file.py
├── write_file.py
└── list_files.py

# Less ideal: generic tool
tools/
└── filesystem_operations.py  # too broad
```

---

## Examples

### Example 1: Code Generation and Execution

```python
from mva.agent import get_agent

agent = get_agent(
    system_prompt="You are a Python expert. Provide clean, well-documented code.",
)

history = [{
    "role": "user",
    "content": "Write a function to check if a number is prime, then test it with 17"
}]

response = agent.run(history)
print(response)
```

### Example 2: Data Analysis with Skills

```python
from mva.agent import get_agent

agent = get_agent(skills_dir="./skills/data-analysis")

history = [{
    "role": "user",
    "content": """
    I have sales data in sales.csv. Use the data-analysis skill to:
    1. Load the data
    2. Calculate summary statistics
    3. Identify trends
    """
}]

for chunk in agent.stream(history):
    if chunk["type"] == "content":
        print(chunk["content"], end="", flush=True)
```

### Example 3: Custom Tool

```python
from mva.agent import get_agent, sandbox, register_tool

@sandbox
def search_docs(query: str) -> str:
    """Search documentation for a query."""
    # Implementation
    return results

agent = get_agent()
register_tool(search_docs)

history = [{"role": "user", "content": "Find docs about authentication"}]
response = agent.run(history)
```

---

## Advanced: Custom LLM Client

```python
from mva.utils.llm_client import BaseLLMClient
from mva.agent import Agent

class CustomClient(BaseLLMClient):
    def complete_stream(self, messages, **kwargs):
        # Custom streaming logic
        pass
    
    def complete(self, messages, **kwargs) -> str:
        # Custom completion logic
        pass
    
    def chat(self, messages, **kwargs) -> dict:
        # Custom chat logic
        pass
    
    def ls_models(self):
        return [{"id": "custom-model"}]

client = CustomClient()
agent = Agent(client=client)
```

See [LLM_CLIENTS.md](LLM_CLIENTS.md) for details on supported clients.

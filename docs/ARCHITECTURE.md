# Architecture Overview

MVA (Minimally Viable Agent) is a modular, extensible Python agent framework with tool-calling and skill discovery.

## High-Level Design

```
┌─────────────────────────────────────────────────┐
│ User Application / CLI                          │
│ (python -m mva chat / mva.test / mva.list)      │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│ Agent Orchestration Layer                       │
│ (Agent.stream() / Agent.run() / Agent.complete) │
├─────────────────────────────────────────────────┤
│ • Message history management                    │
│ • Tool execution loop                           │
│ • Skill catalog integration                     │
│ • Error handling & retries                      │
└────────┬─────────────────┬─────────────────┬────┘
         │                 │                 │
    ┌────▼──────┐   ┌──────▼──────┐   ┌──────▼─────┐
    │ LLM       │   │ Tools       │   │ Skills     │
    │ Clients   │   │ Registry    │   │ Catalog    │
    ├───────────┤   ├─────────────┤   ├────────────┤
    │ OpenAI    │   │ • read_file │   │ • Load     │
    │ Anthropic │   │ • write_file│   │ • Inject   │
    │ Custom    │   │ • exec_code │   │ • Cache    │
    └───────────┘   └─────────────┘   └────────────┘
```

## Core Components

### 1. Agent (`src/mva/agent/base.py`)

**Responsibility:** Orchestrate LLM communication with tool-calling loop

```python
class Agent:
    - stream()      # Streaming responses with tool execution
    - run()         # Non-streaming tool loop
    - complete()    # Pure text completion (no tools)
    
    # Internal
    - _execute_tool()  # Execute tools with error handling
    - _build_messages() # Add system prompt
    - _tool_schemas()   # Get OpenAI-format tool schemas
```

**Key behaviors:**
- Accumulates tool calls from streaming response
- Executes tools and appends results to history
- Continues loop until no more tool calls
- Respects `max_iterations` limit

### 2. LLM Clients (`src/mva/utils/llm_client.py`)

**Responsibility:** Provide unified interface to different LLM backends

```
BaseLLMClient (abstract)
  ├── OpenAIClient
  │   • Handles OpenAI-compatible APIs (vLLM, Ollama, etc.)
  │   • No format conversion needed
  │   • Direct JSON payload to /chat/completions endpoint
  │
  └── AnthropicClient
      • Handles Anthropic Claude API
      • Converts OpenAI format ↔ Anthropic format
      • Maps tool calls to tool_use blocks
```

**Provider detection:**
```
1. Check LLM_PROVIDER env var (explicit)
2. Auto-detect from API keys (ANTHROPIC_API_KEY)
3. Default to OpenAIClient
```

### 3. Tools System (`src/mva/agent/tools.py`)

**Responsibility:** Discover, register, and execute tools with sandboxing

**Components:**
- `Tool` — Metadata + callable wrapper
- `execute_tool()` — Central execution point
- `@sandbox` — Path-safety decorator
- Tool loader — Auto-discovery from `.py` files

**Tool Schema Generation:**
```python
@sandbox
def read_file(filename: str) -> str:
    """Read a file from the sandbox workspace."""
    ...

# Automatically becomes:
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read a file from the sandbox workspace.",
    "parameters": {
      "type": "object",
      "properties": {"filename": {"type": "string"}},
      "required": ["filename"]
    }
  }
}
```

**Sandbox Design:**
- Single folder enforcement
- Strict path validation
- `SandboxError` on escape attempts
- Applies only to path-like parameters (`filename`, `path`, `dir`, etc.)

### 4. Skills System (`src/mva/agent/skills.py`)

**Responsibility:** Discover and manage skill workflows

**Components:**
- `SkillCatalog` — Discovery and lazy loading
- `load_skill()` tool — LLM can request skill instructions
- `system_prompt_injection()` — Add skill catalog to prompt

**Discovery:**
- Scans for `SKILL.md` files in `skills_dir`
- Parses YAML frontmatter (`name`, `description`)
- Caches modtimes for change detection
- Lazy-loads full content on demand

### 5. Configuration (`src/mva/utils/config.py`)

**Responsibility:** Load and cache configuration

```python
def load_config() -> dict:
    # Search order:
    # 1. ./config.yml (local)
    # 2. ~/.config/private-notebook/config.yml (user)
```

**Config keys:**
- `system_prompt` — Base system prompt
- `tools_dir` — Custom tools location
- `skills_dir` — Skills location
- `soul_file` — Personality file
- `log_level` / `log_file` — Logging config
- `color_scheme` — UI theme
- `LLM_PROVIDER` — Provider selection

### 6. CLI (`src/mva/cli.py`)

**Responsibility:** Command-line interface and chat loop

**Commands:**
- `chat` — Interactive chat with streaming
- `test` — Single-query testing
- `list` — List tools and skills

**Features:**
- Readline history (Unix/Linux/macOS)
- Streaming output with formatting
- Slash commands (`/list`, `/help`, `/exit`)
- Error handling and recovery

---

## Data Flow

### Streaming Chat Flow

```
User Input
    ↓
Add to history: {"role": "user", "content": "..."}
    ↓
Agent.stream()
    ├─ client.complete_stream(messages, tools=schemas)
    │
    ├─ Receive streaming chunks:
    │  ├─ content chunks → yield to UI
    │  └─ tool_call_delta chunks → accumulate
    │
    ├─ Tool calls complete, accumulate into JSON
    │
    ├─ Append assistant message with tool_calls to history
    │
    ├─ For each tool call:
    │  ├─ Extract name and arguments
    │  ├─ execute_tool(name, args)
    │  │  ├─ normalize_arguments()
    │  │  ├─ Find tool in registry
    │  │  ├─ Call tool(**args) with error handling
    │  │  └─ Return {"success": true/false, ...}
    │  └─ Append tool message to history
    │
    └─ Loop if more tool calls, else return
```

### Tool Execution Pipeline

```
Tool Call from LLM
    ↓
{"name": "read_file", "arguments": "{\"filename\": \"test.txt\"}"}
    ↓
base.py: _execute_tool()
    ↓
tools.py: execute_tool()
    ├─ normalize_arguments()
    │  ├─ Parse JSON if string
    │  ├─ Unwrap {"args": {...}} patterns
    │  └─ Return clean dict
    ├─ Find tool in _loaded_tools
    ├─ Call tool(**clean_args)
    │  └─ @sandbox decorator applies:
    │     ├─ For path params: safe_path()
    │     ├─ Validate against sandbox root
    │     ├─ Raise SandboxError if escape attempt
    │     └─ Call tool with sanitized args
    └─ Return {"success": bool, "result": ...}
```

---

## Message Format Handling

### OpenAI Format (Native)

```json
{
  "role": "assistant",
  "content": "Here's the code:",
  "tool_calls": [
    {
      "id": "call_123",
      "type": "function",
      "function": {
        "name": "write_file",
        "arguments": "{\"filename\": \"script.py\", \"content\": \"...\"}"
      }
    }
  ]
}
```

### Anthropic Format

```json
{
  "role": "assistant",
  "content": [
    {"type": "text", "text": "Here's the code:"},
    {
      "type": "tool_use",
      "id": "tool_call_123",
      "name": "write_file",
      "input": {"filename": "script.py", "content": "..."}
    }
  ]
}
```

### Conversion (AnthropicClient)

```
OpenAI ──→ normalize_messages() ──→ Anthropic format
           _convert_messages_to_anthropic()

↓ (response comes back)

Anthropic ──→ _convert_response_to_openai() ──→ OpenAI format
              (tool_use → tool_calls)
```

---

## Extension Points

### 1. Custom LLM Client

Implement `BaseLLMClient`:

```python
class MyLLMClient(BaseLLMClient):
    def complete_stream(self, messages, **kwargs):
        # Your streaming logic
        yield {"type": "content", "content": "..."}
    
    def complete(self, messages, **kwargs) -> str:
        # Non-streaming
        pass
    
    def chat(self, messages, **kwargs) -> dict:
        # With tools
        return {...}
    
    def ls_models(self):
        return [...]
```

Pass to Agent:

```python
agent = Agent(client=MyLLMClient())
```

### 2. Custom Tools

Create in `tools/`:

```python
@sandbox
def my_tool(param: str) -> str:
    """Description of what this does."""
    return result

# Auto-discovered and registered
```

### 3. Custom Skills

Create `SKILL.md` in `skills_dir/`:

```yaml
---
name: my-skill
description: What this skill teaches
---

# Skill Content
Step by step instructions...
```

Auto-discovered via `SkillCatalog`.

### 4. Configuration

Override in `config.yml`:

```yaml
system_prompt: |
  Custom system prompt
tools_dir: ./my_tools
skills_dir: ./my_skills
LLM_PROVIDER: anthropic
```

### 5. Logging

Set in `config.yml`:

```yaml
log_level: DEBUG
log_file: agent.log
log_stdout: true
```

---

## Performance Considerations

### Memory

- **Message history**: Grows with conversation length
  - Long conversations → large context windows
  - Solution: Implement message summarization

- **Tool schemas**: Included in every request
  - Many tools → larger payloads
  - Solution: Use specific, focused tools

### Speed

- **Streaming** vs **non-streaming**:
  - Streaming: Token-by-token response (responsive UI)
  - Non-streaming: Wait for full response (simpler code)

- **Tool loop iterations**:
  - More iterations → longer execution
  - Set `max_iterations` based on task complexity

### Cost (with paid APIs)

- **Input tokens**: Proportional to message history
- **Output tokens**: Proportional to response length
- **Tool calls**: Each iteration adds cost

---

## Error Handling Strategy

```python
Agent.stream()
    ├─ LLMError (400/422) → Check tool schemas
    ├─ LLMError (401) → Check API key
    ├─ LLMError (429) → Rate limited
    ├─ LLMError (5xx) → Server error
    │
    ├─ SandboxError → Path escape attempt
    ├─ ToolsNotSupportedError → Tool not found
    │
    └─ Generic Exception → Log and continue
        (tool error returned to LLM for recovery)
```

The LLM receives failed tool results and can:
- Retry with different arguments
- Use a different tool
- Ask for clarification
- Explain the limitation

---

## Testing Strategy

### Unit Tests

- `test_tools.py` — Tool registration and execution
- `test_sandbox.py` — Path validation
- `test_llm_client.py` — Client format conversion
- `test_skills.py` — Skill discovery

### Integration Tests

- `test_agent.py` — Full tool-calling loops
- `test_cli.py` — Command-line interface

### Manual Testing

```bash
# List tools/skills
uv run mva list

# Single query
uv run mva test "Write a function"

# Interactive
uv run mva chat -v
```

---

## Security Model

### Sandbox

- **Single-folder enforcement**: All paths must stay within `SANDBOX_DIR`
- **Escape detection**: `..` and absolute paths rejected
- **Applied to**: File operations only (not code or content)

### No Code Signing

- LLM can execute arbitrary Python
- Assumes trusted LLM server
- For untrusted inputs: Manual review before execution

### Principle of Least Privilege

- Tools only access sandbox directory
- No network access by default
- No system calls unless explicitly added

---

## See Also

- [AGENT.md](AGENT.md) — Agent class details
- [TOOLS.md](TOOLS.md) — Tool system deep dive
- [SKILLS.md](SKILLS.md) — Skills system and creation
- [LLM_CLIENTS.md](LLM_CLIENTS.md) — Provider support
- [CLI.md](CLI.md) — Command-line reference
- [CONFIGURATION.md](CONFIGURATION.md) — Config file options

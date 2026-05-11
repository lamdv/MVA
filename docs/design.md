# MVA — Architecture & Design

> **MVA (Minimum Viable Agent)** is an interactive, agentic REPL for LLMs. It wraps an OpenAI-compatible chat API with tool-calling, allowing the model to autonomously read files, write files, list directories, and execute sandboxed bash commands — all streamed to a rich terminal UI.

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Architecture Overview](#2-architecture-overview)
3. [The Agent Layer](#3-the-agent-layer)
4. [The Tool System](#4-the-tool-system)
5. [The Skills System](#5-the-skills-system)
6. [The CLI / UI Layer](#6-the-cli--ui-layer)
7. [Configuration System](#7-configuration-system)
8. [Security Architecture](#8-security-architecture)
9. [Data Flow](#9-data-flow)
10. [Event System](#10-event-system)
11. [Extension Points](#11-extension-points)
12. [Key Design Decisions](#12-key-design-decisions)
13. [Monorepo Roadmap (v2.1)](#13-monorepo-roadmap-v21)

---

## 1. Design Philosophy

### Core Principles

| Principle | What it means in practice |
|:---|:---|
| **Minimal dependencies** | SQLite (stdlib) for persistence, no vector DB, no Redis. Only `pyyaml`, `requests`, `rich`, `prompt-toolkit`, and `typer` as external deps. |
| **Tool-driven architecture** | Everything the agent does is a tool. Memory, skills, procedures — all tools. The model decides *when* to use them. |
| **Security-first** | Four-layer security stack (blocklist → path escape → user confirmation → resource limits). Dangerous operations always prompt. |
| **Incremental adoption** | Memory, skills, and advanced features are optional. Without `.mva/memory/` or `.mva/skills/`, MVA works exactly as before. |
| **Transparency** | All state is in plain files: `working.md`, `episodic.jsonl`, SQLite DBs, `SKILL.md` files. The user can `cat`, `grep`, `rm` freely. |
| **OpenAI-compatible by default** | Works with any OpenAI-compatible API out of the box (vLLM, Ollama, LocalAI, DeepSeek, etc.). Provider abstraction via `model.yaml`. |

### Why "Minimum Viable"?

MVA is intentionally **not a framework**. It is a **harness** — enough structure to make an LLM useful as a coding agent, but no more. Features earn their place by being:

1. **Viable** — they solve a real problem for the target use case (coding assistance)
2. **Minimum** — they contribute to the simplest implementation that works

This means MVA intentionally omits things like vector databases, RAG pipelines, MCP servers, or workflow engines in its core. Those can be added as tools or skills without architectural changes.

---

## 2. Architecture Overview

### Package Structure (Current)

```
src/mva/
├── __init__.py          → main() entry point, delegates to cli.app()
├── __main__.py          → `python -m mva`
├── config.py            → model.yaml loader, provider config
├── agent/               → Self-contained agent package
│   ├── __init__.py      → Re-exports LLMClient, Session, ToolDef, …
│   ├── client.py        → OpenAI-compatible HTTP client (streaming + non-streaming)
│   ├── session.py       → Session (conversation history, tool-calling loop)
│   ├── tools/           → Complete tool system
│   │   ├── __init__.py  → Registry init, @_register decorator
│   │   ├── base.py      → ToolDef, Tool ABC, ToolResult, SecurityCheck
│   │   ├── registry.py  → ToolRegistry (discovery, registration, execution)
│   │   ├── path_security.py → Path escape detection for sandboxing
│   │   └── builtin/     → read, write, edit, bash, list_files
│   └── skills/          → Skill discovery and loading
│       └── __init__.py  → SkillDef, discover_skills, build_skills_prompt
├── cli/                 → CLI/UI layer (consumes agent)
│   ├── __init__.py
│   ├── app.py           → Typer entry point, session construction
│   ├── console.py       → prompt-toolkit session, completer
│   ├── renderer.py      → Streaming event renderer
│   └── repl.py          → REPL loop
└── utils/               → Mixed helpers
    └── __init__.py      → System prompt builder, message builder, command dispatch
```

### Dependency Graph

```
cli/ (Typer, rich, prompt-toolkit)
  ↓  imports agent/, config, utils
agent/ (requests, pyyaml)
  ↓  imports config, tools, skills (siblings)
tools/ (no external deps)
  ↓  imports base types
skills/ (no external deps)
config/ (pyyaml)
utils/ (imports agent/, skills, tools)
```

### Three-Layer Architecture

```
┌───────────────────────────────────────────────────────────┐
│                    CLI / UI Layer                         │
│  typer, rich, prompt-toolkit                              │
│  app.py → console.py → repl.py → renderer.py              │
│  Commands: /help, /model, /provider, /tools, /skills      │
├───────────────────────────────────────────────────────────┤
│                    Agent Layer                            │
│  client.py → HTTP to LLM API                              │
│  session.py → tool-calling loop, history                  │
│  tools/ → registry, builtins, security                    │
│  skills/ → SKILL.md discovery                             │
├───────────────────────────────────────────────────────────┤
│                    Config Layer                           │
│  config.py → model.yaml parsing, env fallback             │
└───────────────────────────────────────────────────────────┘
```

---

## 3. The Agent Layer

### 3.1 `LLMClient` (`agent/client.py`)

The `LLMClient` is an HTTP client for OpenAI-compatible chat completion APIs. It supports both streaming and non-streaming modes.

**Key responsibilities:**
- Sends chat completion requests with tool definitions
- Streams SSE responses token-by-token
- Accumulates tool calls across streaming chunks
- Supports runtime reconfiguration (provider/model switching)

**Streaming protocol:**

```
chat_stream(messages, tools) → Generator[StreamingDelta]
```

Each `StreamingDelta` carries:
| Field | Type | Purpose |
|:---|:---|:---|
| `delta` | `str` | Text fragment in *this* chunk |
| `accumulated` | `str` | Full response text so far |
| `thinking_delta` | `str` | Reasoning fragment in *this* chunk |
| `thinking` | `str` | Full reasoning text so far |
| `finish_reason` | `str\|None` | `"stop"`, `"tool_calls"`, `"cancelled"` |
| `usage` | `CompletionUsage\|None` | Token counts (usually last chunk) |
| `tool_calls` | `list[dict]\|None` | Fully accumulated tool calls |

**Key detail:** Tool calls are accumulated across chunks by index. The client maintains `tool_calls_by_idx: dict[int, dict]` and appends argument fragments as they arrive. The full tool calls are emitted in the final delta.

### 3.2 `Session` (`agent/session.py`)

The `Session` is the middle layer between the UI and the LLM client. It owns conversation history and runs the tool-calling loop.

**Constructor parameters:**
| Parameter | Purpose |
|:---|:---|
| `client: LLMClient` | The API client |
| `tools: list[ToolDef]` | Tool definitions sent to the API |
| `system_prompt: str` | Built once by the caller |
| `on_confirm: callable` | Callback for user confirmation prompts |

**Key design: Event-driven output**

The `Session.chat()` method yields **events** (plain dicts) rather than calling UI code directly. This makes the session reusable across different UIs (CLI, web, GUI).

```python
# Session emits events — the UI decides how to render them
for event in session.chat("hello"):
    if event["type"] == "thinking":
        socket.emit("thinking", event["content"])
    elif event["type"] == "delta":
        socket.emit("text", event["content"])
```

**Event types:**
| Constant | Type | Payload |
|:---|:---|:---|
| `THINKING` | `"thinking"` | `{"type": "thinking", "content": str}` |
| `DELTA` | `"delta"` | `{"type": "delta", "content": str}` |
| `TOOL_CALL` | `"tool_call"` | `{"type": "tool_call", "id": str, "name": str, "args": dict}` |
| `TOOL_RESULT` | `"tool_result"` | `{"type": "tool_result", "id": str, "name": str, "content": str, "is_error": bool}` |
| `DONE` | `"done"` | `{"type": "done", "content": str}` |
| `CANCELLED` | `"cancelled"` | `{"type": "cancelled"}` |
| `ERROR` | `"error"` | `{"type": "error", "content": str}` |

**Tool-calling loop (inside `_handle_turn`):**

```
Session.chat(user_message)
    │
    ├─ Append user message to history
    ├─ Build messages with system prompt + history
    │
    └─ _handle_turn(messages) ── loop (max 10 rounds)
         │
         ├─ client.chat_stream(messages, tools) → StreamingDelta
         │    ├─ Yield THINKING events
         │    ├─ Yield DELTA events
         │    └─ Stream tool calls as they arrive (TOOL_CALL events)
         │
         ├─ If finish_reason == "tool_calls":
         │    ├─ Record assistant message with tool_calls in history
         │    ├─ For each tool call:
         │    │    ├─ _execute_with_confirmation(name, args)
         │    │    ├─ Yield TOOL_RESULT event
         │    │    └─ Append tool result to history
         │    └─ Rebuild messages → loop back
         │
         └─ If finish_reason == "stop":
              ├─ Record assistant response in history
              └─ Yield DONE event
```

**Confirmation flow (inside `_execute_with_confirmation`):**

```
execute_tool(name, args)
    │
    ├─ If result.needs_confirmation == True:
    │    ├─ Call on_confirm(message, tool_name, args) → bool
    │    ├─ If approved: execute_tool(name, args, confirmed=True)
    │    └─ If denied: return error ToolResult
    │
    └─ If result.needs_confirmation == False:
         └─ Return result directly
```

---

## 4. The Tool System

### 4.1 Core Types (`agent/tools/base.py`)

**`ToolDef`** — API-facing definition sent to the LLM:
```python
@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
```

**`ToolResult`** — what every tool returns:
```python
@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    needs_confirmation: bool = False
    confirmation_message: str = ""
    confirmation_tool: str = ""
    confirmation_args: dict | None = None
```

**`SecurityCheck`** — path/operation security evaluation:
```python
@dataclass
class SecurityCheck:
    safe: bool
    message: str = ""
    offending_path: str = ""
```

**`Tool`** — ABC for all tools:
```python
class Tool(ABC):
    name: str               # Unique identifier
    description: str         # LLM-facing description
    parameters: dict         # JSON Schema
    prompt_snippet: str | None  # One-liner for system prompt

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult: ...

    def check_security(self, **kwargs) -> SecurityCheck | None:
        return None  # Default: always safe
```

**`FunctionTool`** — adapter wrapping a plain function (backward compat):
```python
class FunctionTool(Tool):
    # Wraps a function from @_register or imperative module
```

### 4.2 Registry (`agent/tools/registry.py`)

The `ToolRegistry` is the central hub. It supports **multi-source discovery**:

| Source | Order | Mechanism |
|:---|:---:|:---|
| Built-in tools | 1 (first) | `register_all()` called at startup |
| Entry points | 2 | `mva.tools` pip entry-point group |
| Project `.mva/tools/` | 3 | Walking up from CWD |
| Global `~/.mva/tools/` | 4 | User's global tools directory |
| CLI `--skill` / `--tool` | 5 | Explicit paths |

**Registration convention (file-based / imperative):**

A `.py` file in `.mva/tools/` is a valid tool if it has module-level:

```python
name = "my_tool"
description = "What it does"
parameters = {"type": "object", "properties": {...}}

def execute(**kwargs):
    return "result"  # or ToolResult

def check_security(**kwargs):
    return None  # or {"safe": False, "message": "..."}
```

### 4.3 Built-in Tools (`agent/tools/builtin/`)

| Tool | File | Description |
|:---|:---|:---|
| `read` | `read.py` | Read text/image files (supports offset/limit, 50KB cap) |
| `write` | `write.py` | Write content (auto-creates dirs) |
| `edit` | `edit.py` | Search-and-replace file editing with diff output |
| `list_files` | `list_files.py` | Recursive directory listing (depth/limit) |
| `bash` | `bash.py` | Sandboxed command execution with rlimits |
| `ls` | `__init__.py` | Alias for `list_files` |


### 4.4 Security (`agent/tools/path_security.py`)

See [§8 Security Architecture](#8-security-architecture) for full details.

---

## 5. The Skills System

### 5.1 What is a Skill?

A **skill** is an on-demand capability package. Each skill is a directory containing a `SKILL.md` file with instructions for the model.

```
.mva/skills/
├── example-skill/
│   └── SKILL.md
└── testing/
    └── SKILL.md
```

Skills follow the [Agent Skills](https://agentskills.io) convention.

### 5.2 Discovery (`agent/skills/__init__.py`)

Skills are discovered from:
1. `~/.mva/skills/` (global) — loaded first
2. `.mva/skills/` (project) — walking **up** from CWD, closest wins
3. Extra dirs from `--skill` CLI flags

Duplicates by name are resolved: **closest to CWD wins**.

### 5.3 System Prompt Integration

Skills are injected into the system prompt as an XML-like reference block:

```xml
The following skills provide specialized instructions for specific tasks.
Use the read tool to load a skill's SKILL.md when the task matches.

<available_skills>
  <skill>
    <name>example-skill</name>
    <location>/home/user/project/.mva/skills/example-skill/SKILL.md</location>
    <description>Example Skill</description>
  </skill>
</available_skills>
```

The model is told to `read` the `SKILL.md` file **only when the task matches**. This avoids bloating the context window with irrelevant skill content.

### 5.4 Toggle at Runtime

Skills can be enabled/disabled at runtime:
- `/skills` — list all skills with ON/OFF status
- `/skill:<name>` — toggle a specific skill

State is persisted only for the current session.

---

## 6. The CLI / UI Layer

### 6.1 Typer Entry Point (`cli/app.py`)

The `app` function serves as both the interactive REPL and the non-interactive single-run mode:

```
uv run mva                          # Interactive REPL
uv run mva "list all files"          # Single-run (auto-deny confirmations)
uv run mva --print "hello"           # Print-only mode
uv run mva --skill ./my-skill        # Load extra skills
```

**Startup sequence:**

```
app()
  ├─ install_signal_handler() — Ctrl+C handling
  ├─ discover_skills() + set_skills()
  ├─ Read piped stdin + CLI args → user_message
  ├─ Create LLMClient
  │
  ├─ If print_mode or message:
  │    └─ _run_single(client, message, skills)
  │
  └─ If interactive:
       ├─ print_header()
       ├─ get_tool_defs()
       ├─ build_system_prompt(tools, skills)
       ├─ Create Session(client, tools, system_prompt)
       ├─ _create_prompt_session()
       └─ _repl(pt_session, client, history, agent_session, skills)
```

### 6.2 REPL Loop (`cli/repl.py`)

The REPL is intentionally thin — it delegates to `Session` for all agent logic:

```
loop:
    raw = prompt("You: ")
    if raw == "": continue
    if raw starts with "/": handle_command(); continue
    
    rebuild system_prompt (fresh for skill/AGENT.md changes)
    reset_renderer()
    
    for event in session.chat(raw):
        render_event(event)
```

**Confirmation callback:**
```python
def _confirm_callback(message, tool, args) -> bool:
    print Panel(title="⚠ Security Check", message)
    answer = input("Proceed? [y/N]: ")
    return answer in ("y", "yes")
```

### 6.3 Prompt Toolkit Console (`cli/console.py`)

- **`MVACompleter`** — dynamic tab completion for commands, model names, provider names, skill names
- **Bottom toolbar** — shows current provider/model
- **File history** — stored at `~/.config/mva/history`
- **Key bindings** — Ctrl+C / Ctrl+D to exit

### 6.4 Event Renderer (`cli/renderer.py`)

The `EventRenderer` manages phase transitions within a single turn:

```
Phase diagram for one turn:

  [Thinking] → dim italic text (optional, if model provides reasoning)
       ↓ finish thinking
  [Content]  → bold cyan text (regular response)
       ↓ tool call detected
  [Tool Call] → yellow header with JSON args
       ↓ tool returns
  [Tool Result] → green (success) / red (error) preview
       ↓ (loop back to Thinking or Content if more tool rounds)
  [Done]     → (nothing to render, content already streamed)
```

State is tracked via `thinking_emitted` and `content_started` flags, reset between turns.

### 6.5 Commands (`utils/__init__.py`)

| Command | Handler | Description |
|:---|:---|:---|
| `/exit`, `/quit` | `goodbye(); return False` | Exit the REPL |
| `/clear`, `/reset` | `history.clear()` | Clear conversation |
| `/help` | `print_help()` | Show command table |
| `/history` | Iterate history | Show recent turns |
| `/model` | `_print_model_info()` | Show current model |
| `/model <name>` | `_switch_model()` | Switch model |
| `/provider` | `_list_providers()` | List providers |
| `/provider <name>` | `_switch_provider()` | Switch provider |
| `/tools` | `_print_tools()` | List registered tools |
| `/skills` | `_print_skills()` | List skills with status |
| `/skill:<name>` | `_toggle_skill()` | Toggle skill on/off |

---

## 7. Configuration System

### 7.1 The `model.yaml` File

Configuration is loaded from `model.yaml` in search order:

```
1. ./.mva/model.yaml        ← Project-level (recommended)
2. ~/.config/mva/model.yaml ← User-level global
3. Environment variables     ← Legacy fallback
```

**Format:**
```yaml
provider: openai  # Active provider key

providers:
  openai:
    type: openai
    base_url: http://127.0.0.1:8002/v1
    api_key: no-key
    default_model: gemma-4-4B-it
    models:                     # Optional: runtime-switchable list
      - gemma-4-4B-it
    timeout: 120

  ollama:
    type: openai
    base_url: http://localhost:11434/v1
    api_key: no-key
    default_model: llama3.2
    models: [llama3.2, mistral]

sandbox_dir: ./sandbox
```

### 7.2 Provider Abstraction

The active provider is resolved via `config.get_active_provider()`. Switching providers at runtime:

```
/model ollama      → client.switch_provider("ollama")
/model deepseek    → client.switch_provider("deepseek")
/model ollama/llama3.2 → switch provider + set model
```

### 7.3 Config Data Types

```python
@dataclass
class ProviderConfig:
    type: str = "openai"
    base_url: str = "http://127.0.0.1:8002/v1"
    api_key: str = "no-key"
    default_model: str = ""
    models: list[str] = field(default_factory=list)
    timeout: int = 120

@dataclass
class ModelConfig:
    provider: str = "openai"
    providers: dict[str, ProviderConfig] = ...
    sandbox_dir: str = "./sandbox"
```

---

## 8. Security Architecture

MVA implements a **four-layer security stack**, inspired by the principle of defense in depth.

### Layer 0 — Blocklist (Unconditional)

Patterns in `_DANGEROUS_PATTERNS` are blocked **before any execution**:

| Pattern | Label |
|:---|:---|
| `rm -rf /` or `rm -rf ~` | Dangerous filesystem destruction |
| `mkfs.*` | Filesystem formatting |
| `dd if=.. of=/dev` | Raw device writes |
| `sudo` | Privilege escalation |
| `su` | Switch user |
| Fork bomb regex | Denial of service |
| `curl ... \| bash` | Remote code execution |
| `wget ... \| bash` | Remote code execution |
| `nc -l -e` | Netcat backdoor |

### Layer 1 — Path Escape Detection (`path_security.py`)

Two functions implement path-escape checking:

**`check_file_path_escape(path, cwd, operation)`** — for file tools:
- Expands `~` prefix
- Resolves absolute paths
- Resolves relative paths against CWD
- Follows symlinks (a symlink inside CWD pointing outside is flagged)
- Blocks paths outside CWD

**`check_bash_escape(command, cwd)`** — for bash commands:
- Scans command string for absolute system paths (`/etc`, `/proc`, `/sys`, `/dev`, `/boot`, `/root`)
- Scans for home-escape patterns (`~/`, `~/.ssh`, `~/.aws`, `$HOME`)
- Resolves concrete path-like tokens found in the command
- Allows system binary prefixes (`/usr/`, `/bin/`, `/opt/`, etc.)
- Returns unsafe if any resolved path is outside CWD

### Layer 2 — User Confirmation

When Layer 1 (or a tool's own `check_security()`) reports unsafe, the tool **does not execute**. Instead, `ToolResult(needs_confirmation=True)` is returned. The REPL:

1. Displays a yellow-bordered Panel with the security message
2. Prompts: `Proceed? [y/N]`
3. If approved, re-calls `execute_tool(name, args, confirmed=True)`
4. If denied, returns an error result

### Layer 3 — Resource Limits (Bash Only)

Applied via `resource.setrlimit()` in the subprocess preexec:

| Limit | Value | Purpose |
|:---|:---|:---|
| `RLIMIT_AS` | 512 MB | Address space (memory) |
| `RLIMIT_CPU` | 30 seconds | CPU time |
| `RLIMIT_FSIZE` | 50 MB | File size |
| `RLIMIT_NPROC` | — | Number of processes (inherited) |

Additionally:
- **Command timeout**: configurable (default 30s safety net)
- **Output truncation**: last 2000 lines or 50KB
- **Environment sandboxing**: `HOME=CWD`, `PATH` restricted, `SHELL=/bin/bash`
- **Process group isolation**: `start_new_session=True` enables killing the entire process tree on timeout

---

## 9. Data Flow

### 9.1 Normal Interaction (No Tool Calls)

```
User: "What is the capital of France?"
  │
  ├─ Session.chat("What is the capital of France?")
  │    ├─ history.append({"role": "user", "content": "..."})
  │    ├─ messages = build_messages(system_prompt, history, "")
  │    └─ _handle_turn(messages)
  │         │
  │         ├─ client.chat_stream(messages, tools) → SSE chunks
  │         │    └─ Yield StreamingDelta.delta = "The capital of …"
  │         │         → UI renders "The capital of …"
  │         │    └─ Yield StreamingDelta.finish_reason = "stop"
  │         │
  │         ├─ history.append({"role": "assistant", "content": "..."})
  │         └─ Yield DONE event
  │
  └─ UI: renders final response
```

### 9.2 Tool-Calling Interaction

```
User: "Read the file and summarize it"
  │
  ├─ Session.chat("Read the file and summarize it")
  │    ├─ client.chat_stream() → no final text, finish_reason = "tool_calls"
  │    │    └─ tool_calls: [{id: "call_1", function: {name: "read", args: {path: "README.md"}}}]
  │    │
  │    ├─ history.append(assistant message with tool_calls)
  │    │
  │    ├─ execute_tool("read", {path: "README.md"})
  │    │    ├─ check_bash... wait, no — check_file_path_escape("README.md", cwd)
  │    │    ├─ safe → proceed without confirmation
  │    │    └─ returns ToolResult(content="# MVA...")
  │    │
  │    ├─ history.append({"role": "tool", "tool_call_id": "call_1", "content": "# MVA..."})
  │    │
  │    ├─ client.chat_stream(messages_with_result) → new response
  │    │    └─ "Here's a summary of the README..."
  │    │
  │    └─ Yield DONE event
  │
  └─ UI: shows tool call, tool result, then final summary
```

### 9.3 Cancellation Flow

```
User: Ctrl+C during streaming
  │
  ├─ Signal handler sets _cancel_requested = True
  │
  ├─ client.py: iter_lines() loop checks is_cancel_requested()
  │    ├─ If True → break, close HTTP response, yield final delta with finish_reason="cancelled"
  │    └─ (connection is torn down)
  │
  ├─ session.py: detects finish_reason == "cancelled"
  │    ├─ Records partial response in history (if any)
  │    └─ Returns to REPL without executing tool calls
  │
  └─ REPL: prompts for next input
```

---

## 10. Event System

### 10.1 Session Events

All events are plain `dict` objects for maximum portability across UI backends.

```
Event flow within one _handle_turn:

[THINKING]*  [DELTA]*  [TOOL_CALL]*  [TOOL_RESULT]*  [DONE | CANCELLED | ERROR]
    │           │           │              │                │
    │           │           │              │                └─ Turn complete
    │           │           │              └─ Tool execution result
    │           │           └─ Model requested a tool call
    │           └─ Regular text tokens
    └─ Reasoning/thinking tokens
```

### 10.2 Tool-Call Events

Tool calls are emitted **twice** per call:

1. **`TOOL_CALL`** — when the stream first reveals the tool call (before execution)
2. **`TOOL_RESULT`** — after execution completes

The renderer uses `TOOL_CALL` to show a live preview ("⚡ read Calling with arguments: ...") and `TOOL_RESULT` to show the outcome.

### 10.3 Streaming Delta to Event Translation

```
StreamingDelta → Session._handle_turn() → UI Events

  thinking_delta  → {"type": "thinking", "content": delta.thinking_delta}
  delta           → {"type": "delta", "content": delta.delta}
  tool_calls      → {"type": "tool_call", "id": ..., "name": ..., "args": ...}
  finish_reason   → "stop" → {"type": "done", ...}
                  → "tool_calls" → continue loop
                  → "cancelled" → {"type": "cancelled"}
```

---

## 11. Extension Points

### 11.1 Adding a New Tool (Class-Based — Preferred)

```python
from mva.agent.tools.base import Tool, ToolResult, SecurityCheck
from mva.agent.tools.path_security import check_file_path_escape

class MyTool(Tool):
    name = "my_tool"
    description = "Does something useful."
    parameters = {
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": "Path to the file to process.",
            },
        },
        "required": ["filepath"],
    }
    prompt_snippet = "Process a file"

    def check_security(self, filepath: str, **kwargs) -> SecurityCheck | None:
        check = check_file_path_escape(
            filepath, str(Path.cwd()), operation="process"
        )
        return None if check.safe else check

    def execute(
        self, filepath: str, _confirmed: bool = False, **kwargs
    ) -> ToolResult:
        # Implementation
        return ToolResult(content="Done!")
```

Then register it in `agent/tools/builtin/__init__.py`:
```python
def register_all(registry):
    registry.register(MyTool())
```

### 11.2 Adding a Tool (Imperative / File-Based)

Drop a `.py` file in `.mva/tools/`:

```python
# .mva/tools/weather.py
import requests

name = "weather"
description = "Get the current weather for a city."
parameters = {
    "type": "object",
    "properties": {
        "city": {
            "type": "string",
            "description": "City name",
        },
    },
    "required": ["city"],
}

def execute(city: str, **kwargs):
    return ToolResult(content=f"Weather in {city}: sunny, 22°C")
```

### 11.3 Adding a Skill

Create a directory with a `SKILL.md`:

```
.mva/skills/my-skill/
└── SKILL.md
```

The `SKILL.md` contains instructions the model should follow:

```markdown
# My Skill

This skill helps with Python testing using pytest.

## Instructions

Always use pytest for testing. Run tests with:
```bash
uv run pytest -xvs
```

When the user asks about testing, refer to these instructions.
```

### 11.4 Adding a Provider

Add to `model.yaml`:

```yaml
providers:
  my-custom-provider:
    type: openai
    base_url: https://my-api.example.com/v1
    api_key: my-key
    default_model: my-model
    models:
      - my-model
      - my-model-v2
```

Then switch at runtime with `/provider my-custom-provider`.

---

## 12. Key Design Decisions (Interview)

### Q1: "Why does `edit` use search-and-replace instead of line numbers? Isn't that harder for the model?"

**Good question — and yes, it requires more effort from the model. That's intentional.**

Line-number-based editing is brittle. Every tool call that modifies a file shifts line numbers for every subsequent tool call. In a multi-turn agent loop, the model decides `edit line 42`, another tool adds 5 lines above, and suddenly `line 42` is the wrong target. The model has no way to know the file changed under its feet.

Search-and-replace solves this by being **fully deterministic**: the model provides the exact text to find and its replacement. No positional dependency.

But the bigger win is the **self-correcting feedback loop**. When the search block doesn't match:

- **Zero matches** → The `edit` tool returns the closest lines in the file. The model sees "oh, the file has `fooBar` but I searched for `foo_bar` — let me fix my search block."
- **Multiple matches** → The tool reports all occurrence line numbers. The model sees "that function appears three times — I need to include more surrounding context (the class name, the method above) to disambiguate."

This turns a failure into an informative signal. The model learns to provide better context on the next attempt. With line numbers, a failure just gives you a silent wrong result — no feedback at all.

The cost is that the model must be precise about whitespace and indentation. In practice, models handle this well because code is naturally structured and repetitive patterns are rare within a single scope. The `edit` tool's error messages guide the model toward better search blocks iteratively.

### Q2: "Why no embeddings or vector database for memory?"

**Because SQLite `LIKE` queries and a thoughtful key naming convention are enough for v1 — and they come with zero dependencies.**

The core insight is this: **the model curates its own memory**. It decides what's important enough to store, and it chooses descriptive keys. When a model writes `memory_store("user", "password_library", "passlib")`, it's establishing a key-value pair that's trivially retrievable with `WHERE key LIKE '%password%'`.

Embedding-based retrieval would solve a problem MVA doesn't have yet: finding semantically similar facts when you don't know the key. That's a real use case, but it's a **future optimization, not a current necessity**. Here's why:

1. **SQLite is in the stdlib.** No vector DB, no embedding service, no new dependency. This aligns with the "minimum" principle — the simplest thing that works.
2. **Transparency.** Facts are plain text with descriptive keys. The user can `cat semantic.db | grep password` directly. No opaque vector space.
3. **Embeddings can be added as a tool.** Many LLM providers expose embeddings on the same base URL as chat. A `memory_search_semantic` tool is a drop-in addition — no architectural change needed.

The risk of this choice is recall quality. If the model stores "use pytest" under `key="test_framework"`, and later asks "what testing tool do we use?", a `LIKE '%testing%'` query won't find it. But the model is the one doing both the storing and the querying — it learns to use consistent key naming. And if it fails, the user can say "remember, I told you about testing before" which triggers a broader search.

### Q3: "Why plain dicts for events instead of a proper callback API or observer pattern?"

**Plain dicts are the JSON of inter-component communication — they travel anywhere.**

The event system is the boundary between the agent layer and the UI layer. That boundary should be as **porous as possible**. Plain dicts achieve that:

```python
# CLI renders with rich
for event in session.chat("hello"):
    console.print(event)

# Web app serializes to JSON and sends over WebSocket
for event in session.chat("hello"):
    socket.send(json.dumps(event))

# Test asserts on structure
events = list(session.chat("hello"))
assert events[-1]["type"] == "done"
```

No shared interface classes, no UI imports in the agent layer, no adapter pattern. A `TypedDict` can provide type safety if desired, but the dict itself is the contract.

The trade-off is discoverability — you can't `ctrl+click` into event type definitions as easily as you can with a class hierarchy. We mitigate this with a well-documented event type table (see §10.1) and module-level constants (`THINKING = "thinking"`, etc.) that double as documentation and as match values.

### Q4: "Why two ways to define a tool — class-based and imperative?"

**Two audiences, two ergonomics.**

**Class-based** (subclass `Tool`) is the preferred path. It gives you:
- Method organization (`execute()`, `check_security()`)
- Type safety and IDE support
- Clear separation of concerns for complex logic
- Easy reuse through inheritance

All five built-in tools use this style. It's what you'd use for anything non-trivial.

**Imperative** (module-level conventions in a `.py` file) exists for one reason: **lowering the barrier to contribution**. If someone wants to share a tool via pip or drop a file into `.mva/tools/`, they shouldn't have to learn about abstract base classes, method resolution, or the tool hierarchy. They just need:

```python
name = "weather"
description = "Get the weather for a city."
parameters = {"type": "object", ...}

def execute(city: str, **kwargs):
    return ToolResult(content=f"Weather: sunny, 22°C")
```

The `_tool_from_module()` function in `registry.py` detects this convention and wraps it in a `FunctionTool` adapter automatically. The external contributor doesn't even know `FunctionTool` exists.

The risk is inconsistency — some tools are classes, some are modules. But consistency isn't the goal. **Expressiveness is.** The imperative style is the "fast path" for simple tools; the class-based style is the "full path" for complex ones. Both converge to the same `Tool` interface internally.

### Q5: "Why is confirmation handled in-band via `needs_confirmation` instead of out-of-band callbacks?"

**Because the registry's `execute()` should be a pure function — no side channels, no global state, no callbacks to wire up.**

The flow is simple:

```python
# First call: security check
result = registry.execute("write", {"path": "/etc/passwd", "content": "..."})
if result.needs_confirmation:
    # Prompt user, then retry with confirmed=True
    result = registry.execute("write", {"path": "/etc/passwd", "content": "..."}, confirmed=True)
```

No callback passed into the registry. No exception-based control flow. The tool execution is a **query** that returns a result, and that result can say "I can't proceed without approval." The caller (Session) owns the confirmation loop.

What does this buy us?

1. **Testability without mocking.** A test can call `execute()` and assert on `needs_confirmation` without wiring up a fake UI callback.
2. **Composability.** If you want to build a non-interactive tool orchestrator (say, a batch processor), you just check `needs_confirmation` and skip or auto-deny — no callback interface to implement.
3. **No hidden state.** The confirmation `ToolResult` carries everything needed to retry: the tool name, the arguments, and the message. The caller doesn't need to stash state between calls.

The cost is an extra conditional in the call site. That's in `Session._execute_with_confirmation()`, and it's 15 lines of straightforward code.

### Q6: "Why separate `Session` from `LLMClient`? Couldn't the session just be part of the client?"

**`LLMClient` makes HTTP calls. `Session` has conversations. Those are different responsibilities.**

`LLMClient` is a transport: it serializes messages, sends them to an API, and parses the response. It doesn't know about conversations, history, or tool loops. You can use `LLMClient` to:
- Make a single non-streaming completion
- Stream a response token by token
- Send a standalone embedding request (if the provider supports it)

`Session` is a state machine: it maintains history, runs the multi-turn tool loop, and yields events. It doesn't know about HTTP, SSE parsing, or JSON serialization of tool definitions.

The separation matters for **reusability**. A web developer building a frontend for MVA doesn't want to import `rich` or `prompt-toolkit`. With this separation, they can:

```python
from mva_core import Session, LLMClient, get_tool_defs

client = LLMClient()
session = Session(client, get_tool_defs(), system_prompt)

async def handle_message(user_msg: str):
    async for event in session.chat(user_msg):
        if event["type"] == "delta":
            await websocket.send(json.dumps({"text": event["content"]}))
```

No CLI imports. No rendering logic. Just the agent, portable.

The trade-off is a thin abstraction layer — `Session.chat()` mostly delegates to `client.chat_stream()`. But that's fine. The abstraction exists at the right level: `LLMClient` is the "how" (HTTP streaming), and `Session` is the "what" (agent interaction loop).

It also makes testing easier. You can mock `LLMClient` and test the session's tool-loop logic without hitting a real API — the session never knows the difference between a mock and the real client.

---

## 13. Monorepo Roadmap (v2.1)

The current single-package structure (`src/mva/`) has a problem: `utils/__init__.py` mixes core concerns (system prompt building, signal handling) with CLI concerns (command dispatch, display). A web UI cannot reuse `Session` without importing rich/typer.

### Target Structure

```
mva/
├── packages/
│   ├── mva-core/       # Zero CLI deps: pyyaml, requests
│   │   └── src/mva_core/
│   │       ├── agent/       # client.py, session.py
│   │       ├── tools/       # base, registry, builtins, security
│   │       ├── skills/      # discovery, prompt building
│   │       ├── config.py    # model.yaml loader
│   │       └── _system.py   # extracted from utils (system prompt, messages)
│   │
│   └── mva-cli/        # Depends on mva-core + typer, rich, prompt-toolkit
│       └── src/mva_cli/
│           ├── app.py, repl.py, console.py, renderer.py
│           └── _commands.py  # extracted from utils (command dispatch)
├── docs/
└── README.md
```

### Dependency Graph (After)

```
mva-cli ──→ mva-core
              ├── agent/ ──→ config, _system
              ├── tools/  ──→ agent (ToolDef)
              ├── skills/ ── (pure)
              ├── config.py
              └── _system.py
```

`mva-core` has **zero** CLI dependencies — only stdlib + `pyyaml` + `requests`. No `rich`, no `typer`, no `prompt-toolkit`.

---

## Appendix: File Index

| File | Role | Dependencies |
|:---|:---|:---|
| `src/mva/__init__.py` | Entry point → `cli.app()` | — |
| `src/mva/__main__.py` | `python -m mva` | — |
| `src/mva/config.py` | `model.yaml` loader | `pyyaml` |
| `src/mva/agent/__init__.py` | Re-exports | — |
| `src/mva/agent/client.py` | HTTP chat client | `requests` |
| `src/mva/agent/session.py` | Tool-calling loop | `requests` |
| `src/mva/agent/tools/__init__.py` | Registry bootstrap | — |
| `src/mva/agent/tools/base.py` | Tool ABC, types | — |
| `src/mva/agent/tools/registry.py` | Discovery, execution | — |
| `src/mva/agent/tools/path_security.py` | Path/bashescape checks | — |
| `src/mva/agent/tools/builtin/read.py` | File reader | — |
| `src/mva/agent/tools/builtin/write.py` | File writer | — |
| `src/mva/agent/tools/builtin/edit.py` | Search-and-replace | — |
| `src/mva/agent/tools/builtin/list_files.py` | Directory listing | — |
| `src/mva/agent/tools/builtin/bash.py` | Sandboxed bash | — |
| `src/mva/agent/skills/__init__.py` | Skill discovery | — |
| `src/mva/cli/app.py` | Typer entry point | `typer`, `rich` |
| `src/mva/cli/repl.py` | REPL loop | `prompt-toolkit`, `rich` |
| `src/mva/cli/console.py` | Prompt session | `prompt-toolkit` |
| `src/mva/cli/renderer.py` | Event renderer | `rich` |
| `src/mva/utils/__init__.py` | System prompt, commands | `rich` |

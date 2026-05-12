# AGENT.md — MVA (Minimum Viable Agent)

## What is this project?

MVA is an interactive, agentic REPL for LLMs. It wraps an OpenAI-compatible chat API with tool-calling, allowing the model to autonomously read files, write files, list directories, and execute sandboxed bash commands — all streamed to a rich terminal UI.

## Project layout

```
src/mva/
├── __init__.py          → main() entry point, delegates to cli.app()
├── config.py            → model.yaml loader (search: ./.mva/, ~/.config/mva/)
├── agent/               → self-contained agent package
│   ├── __init__.py      → re-exports LLMClient, Session, ToolDef, execute_tool, SkillDef, …
│   ├── client.py        → OpenAI-compatible HTTP client (streaming SSE + non-streaming)
│   ├── session.py       → Session (conversation history, tool-calling loop)
│   ├── tools/           → tool system (ToolDef, Tool, ToolResult, registry, builtins)
│   │   ├── __init__.py  → re-exports base, registry, builtin
│   │   ├── base.py      → ToolDef, Tool ABC, ToolResult, SecurityCheck
│   │   ├── registry.py  → ToolRegistry (discovery, registration, execution)
│   │   ├── path_security.py → path escape detection for sandboxing
│   │   └── builtin/     → read, write, edit, bash, list_files
│   └── skills/          → skill discovery and loading
│       └── __init__.py  → SkillDef, discover_skills, build_skills_prompt
├── cli/                 → CLI/UI layer (consumes agent)
│   ├── app.py           → Typer entry point
│   ├── console.py       → prompt-toolkit session, completer
│   ├── renderer.py      → streaming event renderer
│   └── repl.py          → REPL loop
└── utils/
    └── __init__.py      → UI helpers, system prompt builder, command dispatch
```

## Tech stack

- **Python 3.13+** with `uv` for package management
- **rich** for terminal UI (panels, tables, markdown rendering)
- **requests** for HTTP calls to the inference server
- **pyyaml** for ``model.yaml`` config parsing

## How to run

```bash
uv sync                          # install deps
uv run --package mva python -m mva
```

## Configuration

MVA reads configuration from ``model.yaml``.  It checks these locations
in order (first match wins):

1. **``./.mva/model.yaml``** — project-level config (recommended)
2. **``~/.config/mva/model.yaml``** — user-level global config
3. **Environment variables** — legacy fallback (``LLM_BASE_URL``, ``LLM_API_KEY``, ``DEFAULT_MODEL``)

See ``docs/model_yaml_format.md`` for the full YAML schema.

Example ``.mva/model.yaml``:

| Variable | Default | Purpose |
|:---|:---|:---|
| ``provider`` | ``openai`` | Active provider key (selects from ``providers`` map) |
| ``providers.<name>.base_url`` | ``http://127.0.0.1:8002/v1`` | API endpoint |
| ``providers.<name>.api_key`` | ``no-key`` | API key (``"no-key"`` for local servers) |
| ``providers.<name>.default_model`` | (required) | Model name sent to the server |
| ``providers.<name>.timeout`` | ``120`` | Request timeout in seconds |
| ``sandbox_dir`` | ``./sandbox`` | Sandbox directory for file operations |

## Conventions

### Tool patterns

Tools are class-based (subclassing :class:`~mva.agent.tools.base.Tool`) or
function-based (registered with the `@_register` decorator).

**Class-based (preferred):**

```python
from mva.agent.tools.base import Tool, ToolResult, SecurityCheck

class MyTool(Tool):
    name = "my_tool"
    description = "What it does"
    parameters = {"type": "object", "properties": {...}}

    def execute(self, **kwargs) -> ToolResult: ...
    def check_security(self, **kwargs) -> SecurityCheck | None: ...
```

**Function-based (legacy):**

```python
from mva.agent.tools import _register

@_register(name="tool_name", description="...", parameters={...})
def tool_name(arg1: str, _confirmed: bool = False) -> ToolResult:
    ...
```

Every tool must:
- Return a `ToolResult` (not a raw string)
- Accept `_confirmed: bool = False` if it has security checks
- Call `check_file_path_escape()` or `check_bash_escape()` before file/bash operations
- Return `_confirm_request(check, "tool_name", **args)` when a security check fails

See `docs/adding_tools.md` for the full guide.

### Key data types

| Type | Defined in | Purpose |
|:---|:---|:---|
| `ChatMessage` | `agent/client.py` | A single conversation turn (role, content, tool_calls) |
| `StreamingDelta` | `agent/client.py` | One SSE chunk from streaming |
| `ToolDef` | `agent/tools/base.py` | Tool metadata sent to the API (name, description, parameters) |
| `ToolResult` | `agent/tools/base.py` | Result of executing a tool (content, is_error, needs_confirmation) |
| `SkillDef` | `agent/skills/__init__.py` | Metadata for a loaded skill (name, content, enabled) |
| `SecurityCheck` | `agent/tools/base.py` | Outcome of a path/operation security evaluation |

### Security stack (4 layers)

1. **Layer 0 — Blocklist**: Regex patterns in `_DANGEROUS_PATTERNS` block `rm -rf /`, `sudo`, fork bombs, etc. unconditionally
2. **Layer 1 — Path escape check**: `check_file_path_escape()` / `check_bash_escape()` detect paths outside CWD
3. **Layer 2 — User confirmation**: REPL prompts `Proceed? [y/N]` when Layer 1 fires
4. **Layer 3 — Resource limits**: `RLIMIT_AS` (256MB), `RLIMIT_CPU` (10s), `RLIMIT_FSIZE` (10MB), `RLIMIT_NPROC` (50)

### REPL flow

1. User enters a message (or `/command`)
2. System prompt + tool defs + conversation history → messages list
3. `client.chat_stream()` yields `StreamingDelta` chunks
4. Renderer displays thinking blocks (dim italic) and regular content (bold cyan)
5. If `finish_reason == "tool_calls"`, execute tools, collect results, loop back to step 2 (max 10 rounds)
6. Final assistant response appended to history

### Code style

- `from __future__ import annotations` at the top of every module
- Type hints on all public functions
- Docstrings in reStructuredText / NumPy style
- `_console` is the singleton `rich.console.Console` used throughout
- Private helpers prefixed with `_`
- No external imports beyond the dependency list in `pyproject.toml`

## Docs index

| Document | What it covers |
|:---|---|
| `docs/design.md` | Full architecture, design decisions, data flow, event system |
| `docs/model_yaml_format.md` | `model.yaml` schema and search order |
| `docs/provider_integration.md` | Configuring DeepSeek, Kimi, OpenRouter, Anthropic, VS Code Copilot proxy |
| `docs/adding_tools.md` | Adding new tools (class-based and imperative patterns) |
| `docs/security.md` | Four-layer security model |
| `docs/memory_system.md` | Memory/persistence system |
| `docs/cli_improvements.md` | Planned CLI improvements roadmap (3 phases, ~30 hours total) |
| `docs/v2.1_monorepo_plan.md` | Monorepo split into `mva-core` + `mva-cli` |

## Key files to know

| File | When to edit |
|:---|:---|
| `src/mva/agent/__init__.py` | Adding re-exports from tools/skills |
| `src/mva/agent/client.py` | Changing API client (new endpoints, streaming, params) |
| `src/mva/agent/session.py` | Changing tool-calling loop logic |
| `src/mva/agent/tools/base.py` | Adding new base types (ToolDef, Tool subclasses) |
| `src/mva/agent/tools/registry.py` | Changing tool discovery or registration |
| `src/mva/agent/tools/builtin/` | Adding new built-in tools |
| `src/mva/agent/tools/path_security.py` | Changing sandbox/path security rules |
| `src/mva/agent/skills/__init__.py` | Changing skill discovery or loading |
| `src/mva/cli/repl.py` | Changing REPL flow |
| `src/mva/cli/renderer.py` | Changing event rendering |
| `src/mva/utils/__init__.py` | Changing system prompt, commands, or UI helpers |
| `src/mva/config.py` | Changing config loading (model.yaml parsing, env fallback) |
| `pyproject.toml` | Adding dependencies |

## Adding a new tool (quick start)

1. Subclass `Tool` from `src/mva/agent/tools/base.py` or use `@_register` in `src/mva/agent/tools/__init__.py`
2. Follow the `_confirmed` + `check_file_path_escape` / `check_bash_escape` pattern
3. Return `ToolResult(...)`
4. If class-based, register it in `src/mva/agent/tools/builtin/__init__.py` (builtins) or via discovery
5. Test with `uv run --package mva python -m mva` and type `/tools` to verify it appears

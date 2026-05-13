# AGENT.md — MVA (Minimum Viable Agent)

## What is this project?

MVA is an interactive, agentic REPL for LLMs. It wraps an OpenAI-compatible chat API with tool-calling, allowing the model to autonomously read files, write files, list directories, and execute sandboxed bash commands — all streamed to a rich terminal UI.

The project is structured as a **uv workspace monorepo** with two packages:

- **`mva-core`** — Agent logic, tools, skills, and configuration (no UI deps)
- **`mva-cli`** — Terminal UI layer (depends on `mva-core`)

## Project layout

```
mva/
├── pyproject.toml               # uv workspace root
├── packages/
│   ├── mva-core/
│   │   ├── pyproject.toml       # dependencies: pyyaml, requests
│   │   └── src/mva_core/
│   │       ├── __init__.py      # flat re-exports
│   │       ├── _system.py       # system prompt builder, signal handling
│   │       ├── config.py        # model.yaml loader
│   │       ├── agent/
│   │       │   ├── __init__.py  # re-exports LLMClient, Session, etc.
│   │       │   ├── client.py    # OpenAI-compatible HTTP client
│   │       │   ├── session.py   # Session (history, tool-calling loop)
│   │       │   └── types.py     # ChatMessage, StreamingDelta, etc.
│   │       ├── tools/
│   │       │   ├── __init__.py  # re-exports base, registry, builtin
│   │       │   ├── base.py      # ToolDef, Tool ABC, ToolResult, SecurityCheck
│   │       │   ├── registry.py  # ToolRegistry (discovery, registration)
│   │       │   ├── path_security.py  # path escape detection & sandboxing
│   │       │   └── builtin/     # read, write, edit, bash, fetch_url, list_files
│   │       └── skills/
│   │           └── __init__.py  # SkillDef, discover_skills
│   └── mva-cli/
│       ├── pyproject.toml       # dependencies: mva-core, typer, rich, prompt-toolkit
│       └── src/mva_cli/
│           ├── __init__.py      # re-exports app
│           ├── app.py           # Typer entry point
│           ├── _commands.py     # command dispatch, helpers
│           ├── console.py       # prompt-toolkit session, completer
│           ├── plugins/         # plugin discovery
│           ├── renderer.py      # streaming event renderer
│           └── repl.py          # REPL loop
├── src/mva/                     # Shim package (delegates to mva-cli)
│   ├── __init__.py
│   └── __main__.py
├── docs/
├── .mva/                        # project-level config (model.yaml, skills)
└── README.md
```

## Tech stack

- **Python 3.13+** with `uv` for package management
- **rich** for terminal UI (panels, tables, markdown rendering)
- **requests** for HTTP calls to the inference server
- **pyyaml** for ``model.yaml`` config parsing

## How to run

```bash
uv sync                          # install deps for all workspace packages
uv run --package mva-cli python -m mva_cli
# or via shim:
uv run python -m mva
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

Tools are class-based (subclassing :class:`~mva_core.tools.base.Tool`) or
function-based (registered with the `@_register` decorator).

**Class-based (preferred):**

```python
from mva_core.tools.base import Tool, ToolResult, SecurityCheck

class MyTool(Tool):
    name = "my_tool"
    description = "What it does"
    parameters = {"type": "object", "properties": {...}}

    def execute(self, **kwargs) -> ToolResult: ...
    def check_security(self, **kwargs) -> SecurityCheck | None: ...
```

**Function-based (legacy):**

```python
from mva_core.tools import _register

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

### Import paths

| Module | Import path |
|:---|---|
| mva-core agent | `from mva_core.agent import Session, LLMClient` |
| mva-core tools | `from mva_core.tools import ToolDef, ToolResult, execute_tool` |
| mva-core tools (base) | `from mva_core.tools.base import Tool, SecurityCheck` |
| mva-core config | `from mva_core.config import load_config` |
| mva-core skills | `from mva_core.skills import discover_skills` |
| mva-cli | `from mva_cli import app` |

### Key data types

| Type | Defined in | Purpose |
|:---|:---|:---|
| `ChatMessage` | `mva_core.agent/types.py` | A single conversation turn (role, content, tool_calls) |
| `StreamingDelta` | `mva_core.agent/types.py` | One SSE chunk from streaming |
| `ToolDef` | `mva_core.tools/base.py` | Tool metadata sent to the API (name, description, parameters) |
| `ToolResult` | `mva_core.tools/base.py` | Result of executing a tool (content, is_error, needs_confirmation) |
| `SkillDef` | `mva_core.skills/__init__.py` | Metadata for a loaded skill (name, content, enabled) |
| `SecurityCheck` | `mva_core.tools/base.py` | Outcome of a path/operation security evaluation |

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
| `packages/mva-core/src/mva_core/agent/__init__.py` | Adding re-exports from tools/skills |
| `packages/mva-core/src/mva_core/agent/client.py` | Changing API client (new endpoints, streaming, params) |
| `packages/mva-core/src/mva_core/agent/session.py` | Changing tool-calling loop logic |
| `packages/mva-core/src/mva_core/tools/base.py` | Adding new base types (ToolDef, Tool subclasses) |
| `packages/mva-core/src/mva_core/tools/registry.py` | Changing tool discovery or registration |
| `packages/mva-core/src/mva_core/tools/builtin/` | Adding new built-in tools |
| `packages/mva-core/src/mva_core/tools/path_security.py` | Changing sandbox/path security rules |
| `packages/mva-core/src/mva_core/skills/__init__.py` | Changing skill discovery or loading |
| `packages/mva-cli/src/mva_cli/repl.py` | Changing REPL flow |
| `packages/mva-cli/src/mva_cli/renderer.py` | Changing event rendering |
| `packages/mva-cli/src/mva_cli/_commands.py` | Changing command dispatch or display helpers |
| `packages/mva-core/src/mva_core/config.py` | Changing config loading (model.yaml parsing, env fallback) |
| `pyproject.toml` (root) | Workspace member management, dev dependencies |

## Adding a new tool (quick start)

1. Subclass `Tool` from `packages/mva-core/src/mva_core/tools/base.py` or use `@_register` in `packages/mva-core/src/mva_core/tools/__init__.py`
2. Follow the `_confirmed` + `check_file_path_escape` / `check_bash_escape` pattern
3. Return `ToolResult(...)`
4. If class-based, register it in `packages/mva-core/src/mva_core/tools/builtin/__init__.py` (builtins) or via discovery
5. Test with `uv run --package mva-cli python -m mva_cli` and type `/tools` to verify it appears

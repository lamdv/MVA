# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run interactive chat
uv run mva chat
uv run mva chat -m <model> -s "Custom system prompt" --tools ./tools --skills ./sandbox/engine/skills/ -v

# Run a single query (non-interactive)
uv run mva test "your query here"

# List loaded tools and skills
uv run mva list
```

## Architecture

**MVA** is a Minimally Viable Agent — a Python CLI that wraps a local/remote OpenAI-compatible LLM with tool-calling and skill discovery.

### Configuration

Two config layers, resolved in order:

1. **`.env`** — runtime secrets and server connection (`LLM_BASE_URL`, `DEFAULT_MODEL`, `LLM_API_KEY`, `SANDBOX_DIR`). Copy from `.env.example`.
2. **`config.yml`** — agent behavior (`system_prompt`, `tools_dir`, `skills_dir`, `soul_file`, `log_level`, `color_scheme`). Falls back to `~/.config/private-notebook/config.yml`.

### Core Flow

`get_agent()` in [src/mva/agent/__init__.py](src/mva/agent/__init__.py) is the main factory:
- Reads `config.yml`, loads `soul_file` (prepended to system prompt if set)
- Auto-discovers `tools_dir` and `skills_dir` from config or defaults
- Returns an `Agent` instance with tools and skills wired up

`Agent` in [src/mva/agent/base.py](src/mva/agent/base.py):
- `stream()` — yields streaming chunks, handles the tool-call loop (up to `max_iterations=50`)
- `run()` — non-streaming equivalent
- `complete()` — single-shot, no tool loop

`LlamaClient` in [src/mva/utils/llm_client.py](src/mva/utils/llm_client.py) handles all HTTP to the OpenAI-compatible endpoint. `LLMError` carries `status_code` — the agent uses 400/422 to detect servers that don't support function calling.

### Tools System

[src/mva/agent/tools.py](src/mva/agent/tools.py) maintains a global `_loaded_tools` list. On import, four built-ins auto-register: `read_file`, `write_file`, `list_files`, `code_execution`.

All file tools are wrapped with `@sandbox`, which enforces all paths stay inside the sandbox root (`SANDBOX_DIR` env var, default `/tmp/agent_workspace`). `SandboxError` is raised on escape attempts.

`load_tools_from_directory(path)` scans a directory for `.py` files and registers any public callable with a docstring as a tool. The `tools/` directory in this repo is loaded at startup via `config.yml`.

### Skills System

Skills are markdown files named `SKILL.md` with YAML frontmatter (`name`, `description`). They live under `sandbox/engine/skills/<skill-name>/SKILL.md`.

`SkillCatalog` in [src/mva/agent/skills.py](src/mva/agent/skills.py) scans for `SKILL.md` files, parses frontmatter, and injects a skill catalog into the system prompt. The agent calls `load_skill(name)` as a registered tool to load the full skill body on demand (lazy loading).

### Adding Custom Tools

Drop a `.py` file in `tools/` (or any configured `tools_dir`). Any public function with a docstring is auto-registered. String/Path arguments are automatically sandboxed.

### Adding Custom Skills

Create `sandbox/engine/skills/<skill-name>/SKILL.md` with YAML frontmatter:
```yaml
---
name: skill-name
description: 'What it does. Use when <triggers>.'
---
```
The agent will discover it on next startup (or `SkillCatalog.refresh()`).

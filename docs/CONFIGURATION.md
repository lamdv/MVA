# Configuration Guide

MVA can be configured via `config.yml` file and environment variables.

## Config File Location

MVA searches for configuration in this order:

1. **Local:** `./config.yml` (in current directory)
2. **User:** `~/.config/private-notebook/config.yml` (home directory)

The first found is used. Environment variables override both.

## Configuration Keys

### LLM Settings

#### `LLM_PROVIDER`
**Type:** `string` | **Default:** `auto`

Explicitly select which LLM provider to use.

**Options:**
- `openai` — OpenAI-compatible (vLLM, Ollama, LocalAI, etc.)
- `anthropic` — Anthropic Claude API
- `ollama` — Alias for openai
- `vllm` — Alias for openai
- `localai` — Alias for openai
- `auto` — Auto-detect from API keys (fallback)

**Environment variable:** `LLM_PROVIDER`

```yaml
LLM_PROVIDER: anthropic
```

#### `DEFAULT_MODEL`
**Type:** `string` | **Default:** `model`

Default model to use when not specified via command line.

**Environment variable:** `DEFAULT_MODEL`

```yaml
DEFAULT_MODEL: claude-3-5-sonnet-20241022
```

#### `LLM_BASE_URL`
**Type:** `string` | **Default:** `http://127.0.0.1:8001/v1`

Base URL of your OpenAI-compatible server (vLLM, Ollama, etc).

**Environment variable:** `LLM_BASE_URL`

```yaml
LLM_BASE_URL: http://localhost:8002/v1
```

#### `LLM_API_KEY`
**Type:** `string` | **Default:** `no-key`

API key for OpenAI-compatible servers.

Use `"no-key"` for local servers that don't require authentication.

**Environment variable:** `LLM_API_KEY`

```yaml
LLM_API_KEY: your-api-key-here
```

#### `ANTHROPIC_API_KEY`
**Type:** `string` | **Default:** (none)

API key for Anthropic Claude API.

Required when `LLM_PROVIDER: anthropic`.

**Environment variable:** `ANTHROPIC_API_KEY`

```yaml
# Note: Usually only set via environment variable
# ANTHROPIC_API_KEY: sk-ant-...
```

### Agent Settings

#### `system_prompt`
**Type:** `string` | **Default:** (none)

System prompt injected at the start of every conversation.

Supports multi-line YAML block scalars.

```yaml
system_prompt: |
  You are an expert Python Coding Agent.
  
  ### Core Rules:
  - Write clean, well-documented code
  - Use modern Python idioms
  - Test your code before returning it
  
  ### Tools Available:
  - write_file: Save code to disk
  - code_execution: Run Python code
```

#### `soul_file`
**Type:** `string` | **Default:** (none)

Path to a personality file (SOUL.md) that's prepended to the system prompt.

Useful for keeping agent personality separate from instructions.

```yaml
soul_file: ./kb/soul.md
```

Contents of `kb/soul.md`:
```markdown
# Agent Soul

I am a helpful, curious, and thoughtful assistant.
I explain my reasoning clearly.
I ask clarifying questions when needed.
```

### Directory Settings

#### `tools_dir`
**Type:** `string` | **Default:** (auto-discover)

Directory containing custom tool Python files.

Auto-discovery order (if not set):
1. `./tools/` (local)
2. `~/.config/private-notebook/tools/` (user)

```yaml
tools_dir: ./my_tools
```

#### `skills_dir`
**Type:** `string` | **Default:** (auto-discover)

Directory containing skill definitions (`SKILL.md` files).

Auto-discovery order (if not set):
1. `./sandbox/engine/skills/` (local)
2. `~/.config/private-notebook/skills/` (user)

```yaml
skills_dir: ./my_skills
```

#### `SANDBOX_DIR`
**Type:** `string` | **Default:** `/tmp/agent_workspace`

Base directory where code execution and file operations happen.

All file operations are restricted to stay within this directory.

**Environment variable:** `SANDBOX_DIR`

```yaml
SANDBOX_DIR: /tmp/mva_workspace
```

### Logging Settings

#### `log_level`
**Type:** `string` | **Default:** `INFO`

Logging level for console and file output.

**Options:**
- `DEBUG` — Very detailed (API calls, tool execution, etc.)
- `INFO` — Standard (major events)
- `WARNING` — Issues and warnings only
- `ERROR` — Errors only

```yaml
log_level: DEBUG
```

#### `log_file`
**Type:** `string` | **Default:** (none)

Path to log file. If not set, only console output.

```yaml
log_file: notebook.log
```

#### `log_stdout`
**Type:** `boolean` | **Default:** `true`

Whether to output logs to console.

```yaml
log_stdout: true
```

### UI Settings

#### `color_scheme`
**Type:** `string` | **Default:** `textual-dark`

Color theme for the CLI.

**Built-in options:**
- `textual-dark`
- `textual-light`
- `nord`
- `gruvbox`
- `catppuccin-mocha`
- `catppuccin-latte`
- `dracula`
- `monokai`
- `tokyo-night`
- `solarized-light`

```yaml
color_scheme: gruvbox
```

---

## Complete Example

### config.yml

```yaml
# System prompt
system_prompt: |
  You are an expert Python Coding Agent (Python 3.11+).
  You are practical, precise, and focused on delivering correct, clean code.
  
  ### Core Rules:
  - Solve tasks using reasoning, code writing, and tools
  - Prioritize working, readable code
  - Never hallucinate APIs
  
  ### Tool Usage:
  Use read_file, write_file, code_execution to test code.

# Personality file (optional)
soul_file: ./kb/soul.md

# Directories
tools_dir: ./tools
skills_dir: ./sandbox/engine/skills/

# Logging
log_level: INFO
log_file: notebook.log
log_stdout: true

# UI
color_scheme: gruvbox
```

### .env

```bash
# LLM Provider
LLM_PROVIDER=anthropic
DEFAULT_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_API_KEY=sk-ant-...

# Or for OpenAI-compatible
# LLM_PROVIDER=openai
# LLM_BASE_URL=http://localhost:8002/v1
# DEFAULT_MODEL=llama-2-7b
# LLM_API_KEY=no-key

# Sandbox
SANDBOX_DIR=/tmp/mva_workspace
```

---

## Environment Variable Override

Environment variables take precedence over config files:

```bash
# Override default model
DEFAULT_MODEL=gpt-4 uv run mva chat

# Override provider
LLM_PROVIDER=openai uv run mva test "Hello"

# Multiple overrides
LLM_BASE_URL=http://custom:8002/v1 \
DEFAULT_MODEL=custom-model \
LLM_API_KEY=key \
uv run mva chat
```

---

## Common Configurations

### Anthropic Claude (Recommended)

```yaml
# config.yml
system_prompt: |
  You are an expert Python Coding Agent.
  Write clean, well-documented code.

tools_dir: ./tools
skills_dir: ./sandbox/engine/skills/

log_level: INFO
log_file: notebook.log
```

```bash
# .env
LLM_PROVIDER=anthropic
DEFAULT_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_API_KEY=sk-ant-...
SANDBOX_DIR=./workspace
```

### Local vLLM

```yaml
# config.yml
system_prompt: |
  You are a helpful Python assistant.

tools_dir: ./tools
log_level: DEBUG
```

```bash
# .env
LLM_PROVIDER=openai
LLM_BASE_URL=http://127.0.0.1:8000/v1
DEFAULT_MODEL=meta-llama/Llama-2-7b
LLM_API_KEY=no-key
SANDBOX_DIR=/tmp/mva_workspace
```

### Development Mode

```yaml
# config.yml
system_prompt: |
  You are a Python expert.
  Always write tests.

tools_dir: ./tools
skills_dir: ./my_skills

log_level: DEBUG
log_file: debug.log
log_stdout: true

color_scheme: dracula
```

```bash
# .env
LLM_PROVIDER=anthropic
DEFAULT_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_API_KEY=sk-ant-...
SANDBOX_DIR=./workspace
```

---

## Troubleshooting Configuration

### "Could not load config"

If no config is found, defaults are used. Create one:

```bash
cp config.yml.example config.yml
# Edit config.yml with your settings
```

### Environment variable not working

Make sure you're exporting it:

```bash
export LLM_API_KEY="your-key"
uv run mva chat

# Or inline
LLM_API_KEY="your-key" uv run mva chat
```

### Tools not loading

Check `tools_dir` in config:

```yaml
tools_dir: ./tools
```

And verify the directory exists with Python files:

```bash
ls -la ./tools
```

### Logs not appearing

Check `log_level` and `log_file`:

```yaml
log_level: DEBUG       # Must be DEBUG or INFO
log_file: notebook.log # Write to file
log_stdout: true       # Also to console
```

### Wrong model being used

Check `DEFAULT_MODEL`:

```yaml
DEFAULT_MODEL: claude-3-5-sonnet-20241022
```

Or override via command line:

```bash
uv run mva chat -m different-model
```

---

## See Also

- [CLI.md](CLI.md) — Command-line interface
- [AGENT.md](AGENT.md) — Agent configuration options
- [LLM_CLIENTS.md](LLM_CLIENTS.md) — LLM provider details

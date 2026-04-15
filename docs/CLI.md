# CLI Interface

MVA includes an interactive CLI for chatting with the agent and testing functionality.

## Commands

### `mva chat` — Interactive Chat Session

Start an interactive conversation with the agent.

```bash
uv run mva chat [options]
```

**Options:**
- `-s, --system TEXT` — Custom system prompt (overrides config.yml)
- `-m, --model TEXT` — LLM model to use (overrides DEFAULT_MODEL)
- `--tools PATH` — Custom tools directory
- `--skills PATH` — Custom skills directory
- `-v, --verbose` — Verbose output (show tool calls and partial results)

**Examples:**

```bash
# Start chat with default config
uv run mva chat

# Chat with a specific model
uv run mva chat -m claude-3-5-sonnet-20241022

# Chat with custom system prompt
uv run mva chat -s "You are a Python expert. Be concise."

# Chat with extra tools and skills
uv run mva chat --tools ./custom_tools --skills ./custom_skills -v
```

**Chat Commands:**

Inside the chat, use slash commands:

| Command | Description |
|---------|-------------|
| `/list` | List available tools and skills |
| `/models` | List available LLM models |
| `/help` | Show command help |
| `/exit` or `/quit` | Exit chat |

**Ctrl+C** also exits gracefully.

---

### `mva test` — Single Query Test

Run a single query and get the response (no tool loop).

```bash
uv run mva test "your query here" [options]
```

**Options:**
- `-m, --model TEXT` — LLM model to use

**Examples:**

```bash
# Test a simple query
uv run mva test "What is Python?"

# Test with specific model
uv run mva test "Write a hello world program" -m llama-2-7b
```

---

### `mva list` — List Tools and Skills

Show all available tools and skills without starting chat.

```bash
uv run mva list
```

**Output:**
```
📋 Available Tools:
  • read_file: Read a file from the sandbox workspace...
  • write_file: Write content to a file...
  • list_files: List files in the sandbox...
  • code_execution: Execute Python code inside the sandbox...

🎯 Available Skills:
  • data-analysis: Perform data analysis tasks
  • web-scraping: Extract data from websites
```

---

## Features

### Interactive History

Arrow keys and Ctrl+R work for command history (readline on Unix/Linux/macOS).

History is saved to `~/.mva_history` and loaded on startup.

### Streaming Output

Chat responses stream in real-time, showing:
- ✨ Assistant response text
- 🔧 Tool calls as they happen
- ✓ Tool results (in verbose mode)
- ❌ Errors in red

### Verbose Mode

With `-v/--verbose`, see detailed information:

```
[Request has 3 message(s)]

🔧 Calling read_file...
✓ read_file: Successfully read /path/to/file (156 bytes)
```

---

## Usage Examples

### Example 1: Write Code and Run It

```bash
$ uv run mva chat
🤖 MVA Agent CLI
==================================================
📋 Loaded 4 tool(s)
🎯 Loaded 2 skill(s)

Commands: /exit, /quit, /list
==================================================

You: Write a Python script that calculates fibonacci numbers
🔧 Calling write_file...
✓ write_file: Successfully wrote to file: fibonacci.py
🔧 Calling code_execution...
✓ code_execution: Script executed successfully

[Assistant response about the script...]

You: Now run the script with input 10
🔧 Calling code_execution...
✓ code_execution: fib(10) = 55

[Assistant continues...]

You: /exit
👋 Goodbye!
```

### Example 2: List Available Tools

```bash
$ uv run mva list
📋 Available Tools:
  • read_file: Read a file from the sandbox workspace (single folder only)...
  • write_file: Write content to a file in the sandbox workspace...
  • list_files: List files in the sandbox workspace...
  • code_execution: Execute Python code inside the strict single-folder sandbox...

🎯 Available Skills:
  No skills loaded.
```

### Example 3: Single Query with Specific Model

```bash
$ uv run mva test "Create a JSON schema for a user profile" -m claude-3-5-sonnet-20241022

{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "User Profile",
  "type": "object",
  "properties": {
    "id": { "type": "string", "description": "Unique user identifier" },
    "email": { "type": "string", "format": "email" },
    ...
  }
}
```

---

## Configuration

### From Environment Variables

```bash
# Override LLM provider and model
export LLM_PROVIDER=anthropic
export DEFAULT_MODEL=claude-3-5-sonnet-20241022
export ANTHROPIC_API_KEY=sk-ant-...

uv run mva chat
```

### From config.yml

See [CONFIGURATION.md](CONFIGURATION.md) for config file options.

---

## Troubleshooting

### "Connection refused" error

Make sure your LLM server is running:

```bash
# For local vLLM
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-2-7b \
  --port 8002

# Then in another terminal
uv run mva chat
```

### Tools not loading

Check that:
1. `tools_dir` exists and has `.py` files
2. Functions have docstrings (required for auto-registration)
3. Logs show "Registered X tool(s)"

```bash
# Increase logging to see what happened
# In config.yml: log_level: "DEBUG"
uv run mva chat
```

### Skills not appearing

1. Check `skills_dir` exists and has `SKILL.md` files
2. Each `SKILL.md` must have YAML frontmatter with `name` and `description`
3. Check logs for parse errors

```bash
# List skills to verify they loaded
uv run mva list
```

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `LLM_PROVIDER` | `openai` or `anthropic` (see [LLM_CLIENTS.md](LLM_CLIENTS.md)) |
| `DEFAULT_MODEL` | Default model for `/chat` (can override with `-m`) |
| `LLM_BASE_URL` | For OpenAI-compatible servers |
| `LLM_API_KEY` | API key for OpenAI-compatible servers |
| `ANTHROPIC_API_KEY` | API key for Anthropic |
| `SANDBOX_DIR` | Where to store code execution results |

---

## Exit Codes

- `0` — Success
- `1` — Error (wrong args, LLM error, tool error)
- `130` — Ctrl+C (KeyboardInterrupt)

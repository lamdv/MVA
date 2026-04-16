# MVA — Minimally Viable Agent

A modular, extensible Python agent framework with **tool-calling**, **skill discovery**, and **multiple LLM backends**.

Build intelligent agents that can read files, write code, execute Python, and follow high-level workflows—all with a sandbox for safety.

## Features

✨ **Multi-Provider LLM Support**
- Anthropic Claude API (recommended)
- OpenAI-compatible servers (vLLM, Ollama, LocalAI)
- Easy provider switching via `LLM_PROVIDER` env var

🔧 **Auto-Discoverable Tools**
- Write Python functions, they become agent tools automatically
- Strict sandbox enforcement on file operations
- Argument validation and error handling

🎯 **High-Level Skills**
- Reusable workflows (SKILL.md files)
- Guide agents through complex multi-step tasks
- Lazy-loaded on demand

🚀 **Streaming & Non-Streaming**
- Real-time response streaming
- Tool-calling loop with full transparency
- Multiple LLM clients with unified interface

📊 **Self-Improvement System**
- Observe: Automatic telemetry recording of every tool call
- Reflect: LLM-based analysis to identify patterns and insights
- Improve: Generate new tools and skills from learnings (coming soon)
- Fully opt-in via config, never interferes with normal operation

🛡️ **Security by Default**
- Single-folder sandbox for all file operations
- Path escape detection and prevention
- Sandboxed code execution

## Quick Start

### 1. Install

```bash
git clone <repository>
cd MVA
uv sync
```

### 2. Configure

```bash
# Copy template
cp .env.example .env

# Edit .env and add API key
# For Anthropic:
export ANTHROPIC_API_KEY=sk-ant-...
export LLM_PROVIDER=anthropic
export DEFAULT_MODEL=claude-3-5-sonnet-20241022
```

### 3. Chat

```bash
# Start interactive chat
uv run mva chat

# Or test a single query
uv run mva test "Write a Python function that..."
```

## Usage

### Interactive Chat

```bash
$ uv run mva chat

🤖 MVA Agent CLI
==================================================
📋 Loaded 4 tool(s)
🎯 Loaded 0 skill(s)
==================================================

You: Write a Python script to calculate Fibonacci numbers
🔧 Calling write_file...
🔧 Calling code_execution...
✓ The script has been created and tested...

[Assistant response with results]

You: /list
📋 Available Tools:
  • read_file, write_file, list_files, code_execution

You: /exit
👋 Goodbye!
```

### Programmatic Usage

```python
from mva.agent import get_agent

# Create agent with auto-discovery
agent = get_agent()

# Run with tool-calling loop
history = [{"role": "user", "content": "Write a hello world program"}]
response = agent.run(history)
print(response)

# Or stream responses
for chunk in agent.stream(history):
    if chunk["type"] == "content":
        print(chunk["content"], end="", flush=True)
    elif chunk["type"] == "tool_use":
        print(f"\n✓ {chunk['name']}: {chunk['result'][:100]}...")
```

### Create a Custom Tool

```python
# tools/my_tool.py
from mva.agent.tools import sandbox

@sandbox
def analyze_file(filename: str) -> dict:
    """Analyze a file and return statistics."""
    import os
    path = filename  # Automatically sandboxed
    size = os.path.getsize(path)
    return {"filename": filename, "size": size}
```

Tools are auto-discovered and immediately available to the agent!

### Create a Skill

```yaml
# sandbox/engine/skills/data-analysis/SKILL.md
---
name: data-analysis
description: Perform exploratory data analysis on CSV files
---

# Data Analysis Skill

## Step 1: Load Data
Use code_execution to load the CSV:

\`\`\`python
import pandas as pd
df = pd.read_csv("data.csv")
print(df.head())
\`\`\`

## Step 2: Explore
- Check data types
- Look for missing values
- Calculate summary statistics

## Step 3: Visualize
Plot distributions and correlations.
```

## LLM Providers

### Anthropic Claude (Recommended)

```bash
export LLM_PROVIDER=anthropic
export DEFAULT_MODEL=claude-3-5-sonnet-20241022
export ANTHROPIC_API_KEY=sk-ant-...
```

**Models available:**
- `claude-3-5-sonnet-20241022` (balanced)
- `claude-3-5-haiku-20241022` (fast)
- `claude-3-opus-20250219` (capable)

Get API key: https://console.anthropic.com/

### OpenAI-Compatible (vLLM, Ollama, etc.)

```bash
export LLM_PROVIDER=openai
export LLM_BASE_URL=http://localhost:8002/v1
export DEFAULT_MODEL=meta-llama/Llama-2-7b-hf
export LLM_API_KEY=no-key
```

**Start vLLM:**
```bash
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-2-7b-hf \
  --port 8002
```

## CLI Commands

```bash
# Interactive chat
uv run mva chat [options]
  -s, --system TEXT      Custom system prompt
  -m, --model TEXT       LLM model to use
  --tools PATH           Custom tools directory
  --skills PATH          Custom skills directory
  -v, --verbose          Show tool details

# Single query
uv run mva test "query" [options]
  -m, --model TEXT       LLM model to use

# List tools and skills
uv run mva list
```

## Configuration

Two-level configuration:

1. **`config.yml`** — Agent behavior
   ```yaml
   system_prompt: Your custom prompt
   tools_dir: ./tools
   skills_dir: ./sandbox/engine/skills/
   log_level: DEBUG
   log_file: notebook.log
   ```

2. **`.env`** — Secrets and LLM settings
   ```bash
   LLM_PROVIDER=anthropic
   DEFAULT_MODEL=claude-3-5-sonnet-20241022
   ANTHROPIC_API_KEY=sk-ant-...
   SANDBOX_DIR=/tmp/mva_workspace
   ```

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for complete reference.

## Architecture

```
┌─────────────────┐
│ User / CLI      │
└────────┬────────┘
         │
    ┌────▼──────────────────┐
    │ Agent                 │ Orchestrates LLM calls & tool loop
    │ • stream()            │
    │ • run()               │
    │ • complete()          │
    └────┬──────────────────┘
         │
    ┌────┴─────┬──────────┬──────────┐
    │          │          │          │
┌───▼───┐ ┌────▼───┐ ┌────▼───┐ ┌────▼────┐
│ LLM   │ │ Tools  │ │ Skills │ │ Config  │
│       │ │        │ │        │ │         │
│ • OAI │ │ • Disc │ │ • Load │ │ • YAML  │
│ • Ant │ │ • Exec │ │ • Inj  │ │ • Env   │
└───────┘ └────────┘ └────────┘ └─────────┘
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Built-in Tools

All agents have four built-in tools:

| Tool | Purpose |
|------|---------|
| `read_file(filename)` | Read files from sandbox |
| `write_file(filename, content)` | Write files to sandbox |
| `list_files(path)` | List directory contents |
| `code_execution(code)` | Execute Python code in sandbox |

## Security

✅ **Sandbox Enforcement**
- All file operations restricted to `SANDBOX_DIR`
- Path escape attempts blocked (e.g., `../../etc/passwd`)
- Raises `SandboxError` on violation

⚠️ **No Code Signing**
- LLM can execute arbitrary Python
- Assumes trusted LLM server
- For untrusted inputs: Manual review before execution

## Documentation

Start with quick setup, then dive into specific guides:

- **[docs/QUICKSTART.md](docs/QUICKSTART.md)** — 5-minute setup
- **[docs/CLI.md](docs/CLI.md)** — CLI reference
- **[docs/AGENT.md](docs/AGENT.md)** — Agent API & examples
- **[docs/TOOLS.md](docs/TOOLS.md)** — Creating tools
- **[docs/SKILLS.md](docs/SKILLS.md)** — Creating skills
- **[docs/LLM_CLIENTS.md](docs/LLM_CLIENTS.md)** — LLM providers
- **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)** — Config reference
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — System design
- **[docs/README.md](docs/README.md)** — Documentation index

## Examples

### Example 1: Data Analysis

```python
from mva.agent import get_agent

agent = get_agent()

task = """
I have a CSV file with sales data. Please:
1. Load the data
2. Calculate total sales by region
3. Find the top 3 regions
4. Save results to output.json
"""

response = agent.run([{"role": "user", "content": task}])
print(response)
```

### Example 2: Code Generation

```bash
uv run mva test "Create a Python class for a linked list with insert, delete, and search methods"
```

### Example 3: Custom Workflow

```python
from mva.agent import Agent
from mva.utils.llm_client import get_client
from pathlib import Path

agent = Agent(
    client=get_client(),
    system_prompt="You are a Python expert. Write production-quality code.",
    tools_dir=Path("./custom_tools"),
    skills_dir=Path("./custom_skills"),
)

history = [{"role": "user", "content": "Help me debug this code..."}]
response = agent.run(history)
```

### Example 4: Self-Improvement (Observe & Reflect)

Enable the agent to learn from its own tool usage and generate insights:

```yaml
# config.yml
self_improvement:
  telemetry_dir: sandbox/telemetry
  reflect_always: true
  fail_rate_threshold: 0.3
  slow_tool_threshold_ms: 5000
```

Then run sessions normally:

```bash
# Session 1: Agent records telemetry
uv run mva test "Analyze this CSV file and generate a report"

# Check what was recorded
cat sandbox/telemetry/sessions/*.json | python -m json.tool

# View reflections (LLM analysis of tool usage)
cat sandbox/telemetry/reflections/*.md
```

**What happens:**
1. **Observe** — Every tool call is recorded: name, args, success/failure, latency
2. **Reflect** — After the session, an LLM analyzes the telemetry and generates insights
3. **Improve** — Agent learns to generate new tools for missing capabilities (Phase 3, coming soon)

See [SELF_IMPROVEMENT.md](SELF_IMPROVEMENT.md) and [docs/SELF_IMPROVEMENT_PLAN.md](docs/SELF_IMPROVEMENT_PLAN.md) for details.

## Project Structure

```
MVA/
├── src/mva/
│   ├── agent/
│   │   ├── base.py        # Agent class
│   │   ├── tools.py       # Tool system
│   │   ├── skills.py      # Skill discovery
│   │   └── __init__.py    # Exports
│   ├── utils/
│   │   ├── llm_client.py  # OpenAI & Anthropic clients
│   │   ├── config.py      # Config loading
│   │   └── log.py         # Logging
│   └── cli.py             # CLI interface
├── tools/                 # Custom tools (auto-discovered)
├── sandbox/
│   └── engine/
│       └── skills/        # Skills (auto-discovered)
├── docs/                  # Documentation
├── config.yml             # Configuration
├── .env.example           # Environment template
├── pyproject.toml         # Dependencies
└── README.md              # This file
```

## Requirements

- Python 3.11+
- `uv` package manager (or `pip`)
- LLM API access (Anthropic or local server)

## Installation Methods

### Using uv (Recommended)

```bash
git clone <repository>
cd MVA
uv sync
uv run mva chat
```

### Using pip

```bash
git clone <repository>
cd MVA
pip install -e .
python -m mva chat
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `auto` | `openai`, `anthropic`, or `auto` |
| `DEFAULT_MODEL` | `model` | Model to use |
| `LLM_BASE_URL` | `http://127.0.0.1:8001/v1` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | `no-key` | API key for OpenAI-compatible |
| `ANTHROPIC_API_KEY` | (none) | Anthropic API key |
| `SANDBOX_DIR` | `/tmp/agent_workspace` | Sandbox root |

## Logging

Enable debug logs to see API calls and tool execution:

```yaml
# config.yml
log_level: DEBUG
log_file: notebook.log
log_stdout: true
```

```bash
# Or via environment
LOG_LEVEL=DEBUG uv run mva chat
```

## Troubleshooting

### "Connection refused"
Your LLM server isn't running. For vLLM:
```bash
python -m vllm.entrypoints.openai.api_server --model ...
```

### "ANTHROPIC_API_KEY not found"
Set in `.env`:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run mva chat
```

### Tools not loading
Check `tools_dir` in `config.yml` and ensure functions have docstrings.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for more troubleshooting.

## Performance

- **Streaming** — Real-time token output (better UX)
- **Non-streaming** — Simpler code, no latency advantage
- **Tool selection** — Fewer, specific tools = faster execution
- **Temperature** — Lower = more focused, higher = more creative

## License

See LICENSE file in repository root.

## Contributing

Contributions welcome! Areas of interest:

- Additional LLM providers
- More built-in tools
- Example skills
- Documentation improvements
- Bug reports and fixes

## Resources

- **[Anthropic Docs](https://docs.anthropic.com/)** — Claude API reference
- **[vLLM](https://docs.vllm.ai/)** — Local LLM serving
- **[OpenAI API Spec](https://platform.openai.com/docs/api-reference)** — Compatible format

## Getting Help

1. **Quick questions** → Check [docs/QUICKSTART.md](docs/QUICKSTART.md)
2. **Configuration** → See [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
3. **Creating tools** → Read [docs/TOOLS.md](docs/TOOLS.md)
4. **Understanding system** → Review [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
5. **API reference** → See [docs/AGENT.md](docs/AGENT.md)

---

**Ready to get started?** → [QUICKSTART.md](docs/QUICKSTART.md)

**Want to understand the system?** → [ARCHITECTURE.md](docs/ARCHITECTURE.md)

**Need specific guidance?** → [docs/README.md](docs/README.md)

# Quick Start Guide

Get MVA up and running in 5 minutes.

## Prerequisites

- Python 3.11+
- `uv` package manager
- An LLM API (Anthropic or local server)

## Installation

### 1. Clone and Setup

```bash
git clone <repository>
cd MVA
uv sync
```

### 2. Configure LLM

Choose your LLM provider:

**Option A: Anthropic Claude** (Recommended for starting out)

```bash
# Create .env
cp .env.example .env

# Edit .env and add your API key
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=anthropic
DEFAULT_MODEL=claude-3-5-sonnet-20241022
```

Get your API key at https://console.anthropic.com/

**Option B: Local vLLM**

```bash
# Terminal 1: Start vLLM server
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-2-7b-hf \
  --port 8002

# Terminal 2: Configure MVA
cp .env.example .env
# Edit .env
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:8002/v1
DEFAULT_MODEL=meta-llama/Llama-2-7b-hf
LLM_API_KEY=no-key
```

**Option C: Ollama**

```bash
# Start Ollama (https://ollama.ai)
ollama pull llama2
ollama serve  # Runs on http://localhost:11434

# Configure MVA
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:11434/v1
DEFAULT_MODEL=llama2
LLM_API_KEY=no-key
```

### 3. Verify Installation

```bash
# List available tools and skills
uv run mva list

# Should show:
# 📋 Available Tools:
#   • read_file: Read a file from the sandbox workspace
#   • write_file: Write content to a file...
#   • list_files: List files in the sandbox...
#   • code_execution: Execute Python code inside the sandbox...
```

## Your First Chat

### Start Interactive Chat

```bash
uv run mva chat
```

You should see:

```
🤖 MVA Agent CLI
==================================================
📋 Loaded 4 tool(s)
🎯 Loaded 0 skill(s)

Commands: /exit, /quit, /list
==================================================

You: 
```

### Try Simple Commands

```
You: Hello! What can you do?
🤖 I can write Python code, execute it, read and write files...

You: Write a function that returns the factorial of a number
🔧 Calling write_file...
🔧 Calling code_execution...
✓ The function has been written and tested...

You: /list
📋 Available Tools:
  • read_file: Read a file from the sandbox workspace
  • write_file: Write content to a file in the sandbox workspace
  • list_files: List files in the sandbox workspace
  • code_execution: Execute Python code inside the sandbox

You: /exit
👋 Goodbye!
```

## Try a Real Task

```bash
uv run mva chat
```

```
You: Create a Python script that:
1. Generates 10 random numbers between 1 and 100
2. Calculates their average
3. Counts how many are above the average

🔧 Calling write_file...
🔧 Calling code_execution...
✓ code_execution: Successfully executed

[Script output showing results]

You: Now save the results to results.json
🔧 Calling code_execution...
✓ code_execution: Execution completed

You: Read the results file and summarize it
🔧 Calling read_file...

[Summary of results]

You: /exit
```

## Common Commands

### Interactive Chat

```bash
# Start chat with default settings
uv run mva chat

# Chat with specific model
uv run mva chat -m claude-3-5-sonnet-20241022

# Chat with custom system prompt
uv run mva chat -s "You are a Python expert. Be concise."

# Verbose mode (see tool details)
uv run mva chat -v
```

### Single Query

```bash
# Test without interactive loop
uv run mva test "Write a hello world program"

uv run mva test "Explain how Python lists work" -m llama2
```

### List Tools/Skills

```bash
# See what's available
uv run mva list
```

## Configuration

### System Prompt

Edit `config.yml`:

```yaml
system_prompt: |
  You are an expert Python Coding Agent.
  Write clean, well-documented code.
  Always test before returning results.
```

### Logging

```yaml
# config.yml
log_level: DEBUG        # See all details
log_file: agent.log    # Save to file
log_stdout: true       # Also show in console
```

## Next Steps

### Learn More

1. **[AGENT.md](AGENT.md)** — Understand the Agent system
2. **[TOOLS.md](TOOLS.md)** — Create custom tools
3. **[SKILLS.md](SKILLS.md)** — Build skill workflows
4. **[CONFIGURATION.md](CONFIGURATION.md)** — Full config reference

### Create a Custom Tool

```python
# tools/greet.py
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}! Welcome to MVA."
```

Restart chat and try:

```
You: Can you greet Alice?
🔧 Calling greet...
Hello, Alice! Welcome to MVA.
```

### Create a Custom Skill

```yaml
# sandbox/engine/skills/hello/SKILL.md
---
name: hello
description: Learn to use MVA
---

# Hello Skill

This is a sample skill.

## Step 1: Learn about tools
MVA has four built-in tools: read_file, write_file, list_files, code_execution

## Step 2: Learn about skills
Skills are high-level workflows that guide you through tasks.
```

Then in chat:

```
You: /list
🎯 Available Skills:
  • hello: Learn to use MVA
```

## Troubleshooting

### "Connection refused"

LLM server isn't running. For vLLM:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-2-7b-hf
```

### "ANTHROPIC_API_KEY not found"

Set in `.env` or as environment variable:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run mva chat
```

### "No tools loaded"

Check `tools_dir` in `config.yml` or run:

```bash
uv run mva list
```

Tools must be in `./tools/` directory and have docstrings.

### Tools not appearing

```bash
# Debug: run with verbose logging
# In config.yml:
log_level: DEBUG

uv run mva list

# Check logs for tool loading messages
```

## Tips

### Keep Conversations Focused

Don't try everything at once:

```
✓ Good: "Write a Python function to sort a list"
✗ Bad: "Write 5 functions, test them, document them, create a UI"
```

### Use Verbose Mode for Learning

```bash
uv run mva chat -v
```

You'll see exactly what tools are being called and their results.

### Check Available Models

```bash
# List available models for your provider
uv run mva chat
You: /models
Available models:
  • claude-3-5-sonnet-20241022
  • claude-3-5-haiku-20241022
```

### Save Important Conversations

Logs are saved to `notebook.log` (if configured):

```yaml
# config.yml
log_file: notebook.log
log_level: INFO
```

### Experiment with Temperature

For more creative responses:

```bash
# Create a modified Agent with higher temperature
# In your Python code:
from mva.agent import Agent
from mva.utils.llm_client import get_client

agent = Agent(
    client=get_client(),
    temperature=0.9  # Higher = more creative
)
```

## What's Next?

### To Learn the Agent System
→ Read [AGENT.md](AGENT.md)

### To Create Tools
→ Read [TOOLS.md](TOOLS.md)

### To Understand Everything
→ Read [ARCHITECTURE.md](ARCHITECTURE.md)

### To Get Help with Configuration
→ Read [CONFIGURATION.md](CONFIGURATION.md)

### To Work with Skills
→ Read [SKILLS.md](SKILLS.md)

## FAQ

**Q: Can I use multiple tools in one request?**
A: Yes! The agent calls multiple tools as needed and manages the loop.

**Q: Can I create tools that call other tools?**
A: Not directly - tools can't call each other. But the agent can orchestrate multiple tool calls in sequence.

**Q: Is there a web interface?**
A: Not in the base repo, but you can embed MVA in your app. See [AGENT.md](AGENT.md) for Python API.

**Q: Can I use this offline?**
A: Yes, with a local LLM like vLLM or Ollama.

**Q: Are my API calls logged?**
A: Yes, set `log_level: DEBUG` in config.yml to see them.

## Have Fun!

MVA is designed to be simple yet powerful. Try:

- Building tools for your workflow
- Creating skills to guide complex tasks
- Embedding it in your Python applications
- Combining it with other tools and APIs

Start small, experiment often, and enjoy building with MVA!

---

**Ready to go deeper?** Check the [Documentation Index](README.md).

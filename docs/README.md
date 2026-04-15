# MVA Documentation

Welcome to the MVA (Minimally Viable Agent) documentation. This guide covers all aspects of using and extending MVA.

## Getting Started

**New to MVA?** Start here:

1. [QUICKSTART.md](QUICKSTART.md) — 5-minute setup and first agent
2. [CLI.md](CLI.md) — Command-line interface overview
3. [CONFIGURATION.md](CONFIGURATION.md) — Configure your agent

## Core Documentation

### Using MVA

- **[CLI.md](CLI.md)** — Command-line interface
  - `mva chat` — Interactive chat
  - `mva test` — Single query
  - `mva list` — List tools and skills

- **[AGENT.md](AGENT.md)** — Agent system
  - Creating agents
  - `run()` vs `stream()` vs `complete()`
  - Tool management
  - Skill integration
  - Error handling

### Extending MVA

- **[TOOLS.md](TOOLS.md)** — Tool system (low-level functions)
  - Creating custom tools
  - Tool discovery
  - Sandbox enforcement
  - Argument normalization

- **[SKILLS.md](SKILLS.md)** — Skill system (high-level workflows)
  - Creating skills
  - Skill structure (SKILL.md format)
  - Using skills in chat
  - Best practices

### LLM Integration

- **[LLM_CLIENTS.md](LLM_CLIENTS.md)** — Supported LLM backends
  - OpenAI-compatible APIs (vLLM, Ollama, LocalAI)
  - Anthropic Claude API
  - Provider selection
  - Format conversion

- **[CONFIGURATION.md](CONFIGURATION.md)** — Configuration
  - Config file (config.yml)
  - Environment variables
  - LLM settings
  - Logging options

### Architecture

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — System design overview
  - Component diagram
  - Data flow
  - Extension points
  - Performance considerations
  - Security model

## Quick Reference

### Installation

```bash
# Clone and setup
git clone <repo>
cd MVA
uv sync

# Create .env from template
cp .env.example .env
# Edit .env with your API keys
```

### First Chat

```bash
# Using Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-...
uv run mva chat

# Using local vLLM
export LLM_BASE_URL=http://localhost:8002/v1
export DEFAULT_MODEL=meta-llama/Llama-2-7b
uv run mva chat
```

### Create a Tool

```python
# tools/my_tool.py
@sandbox
def my_tool(filename: str) -> str:
    """Description of what this tool does."""
    # filename is automatically sandboxed
    return result

# Auto-discovered and available to the agent!
```

### Create a Skill

```yaml
# sandbox/engine/skills/my-skill/SKILL.md
---
name: my-skill
description: What this skill teaches
---

# My Skill

## Step 1: ...
## Step 2: ...
```

### List Tools and Skills

```bash
uv run mva list
```

### Run a Query

```bash
uv run mva test "Your query here"
```

## File Structure

```
MVA/
├── src/mva/
│   ├── agent/
│   │   ├── base.py          # Agent class
│   │   ├── tools.py         # Tool system
│   │   ├── skills.py        # Skill discovery
│   │   └── __init__.py      # Factory functions
│   ├── utils/
│   │   ├── llm_client.py    # LLM backends
│   │   ├── config.py        # Config loading
│   │   └── log.py           # Logging
│   ├── cli.py               # CLI interface
│   └── __init__.py
├── tools/                   # Custom tools (auto-discovered)
├── sandbox/
│   └── engine/
│       └── skills/          # Skills (auto-discovered)
├── config.yml              # Configuration
├── .env                    # Environment variables
└── docs/                   # This documentation
```

## Common Tasks

### I want to...

**Use Claude from Anthropic**
→ See [LLM_CLIENTS.md](LLM_CLIENTS.md) and [CONFIGURATION.md](CONFIGURATION.md)

**Use a local model (vLLM/Ollama)**
→ See [LLM_CLIENTS.md](LLM_CLIENTS.md) and [CONFIGURATION.md](CONFIGURATION.md)

**Create a custom tool**
→ See [TOOLS.md](TOOLS.md) and [AGENT.md](AGENT.md)

**Create a custom skill**
→ See [SKILLS.md](SKILLS.md)

**Configure logging**
→ See [CONFIGURATION.md](CONFIGURATION.md)

**Debug tool calls**
→ Set `log_level: DEBUG` in config.yml

**Understand the architecture**
→ See [ARCHITECTURE.md](ARCHITECTURE.md)

**Embed MVA in my app**
→ See [AGENT.md](AGENT.md) API methods and examples

## Documentation Map

```
You are here
    ↓
[README.md] ← Start
    ├─ [QUICKSTART.md] ← 5 min intro
    ├─ [CLI.md] ← Using the command line
    │
    ├─ User Guide
    │  ├─ [AGENT.md] ← Agent class API
    │  ├─ [LLM_CLIENTS.md] ← LLM providers
    │  └─ [CONFIGURATION.md] ← Configuration
    │
    ├─ Extension Guide
    │  ├─ [TOOLS.md] ← Creating tools
    │  └─ [SKILLS.md] ← Creating skills
    │
    └─ [ARCHITECTURE.md] ← Deep dive
```

## Key Concepts

### Tools vs Skills

| Tools | Skills |
|-------|--------|
| Low-level functions | High-level workflows |
| Direct execution | Multi-step guidance |
| Examples: `read_file()`, `write_file()` | Examples: "Data Analysis", "Web Scraping" |
| Auto-registered | Lazily loaded on request |

### Sandbox

- All file operations restricted to `SANDBOX_DIR`
- Path escape attempts raise `SandboxError`
- Applies only to path-like parameters
- Code execution isolated per session

### LLM Providers

| Provider | Setup | Cost | Speed |
|----------|-------|------|-------|
| Anthropic Claude | Easy, API key | Paid | Fast |
| vLLM (local) | More complex | Free | Depends |
| Ollama | Medium | Free | Slow |

## Troubleshooting

### "Connection refused"

Make sure your LLM server is running:

```bash
# For vLLM
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-2-7b-hf \
  --port 8002
```

### Tools not appearing

1. Check `tools_dir` in config.yml
2. Functions must have docstrings
3. Run `uv run mva list` to verify

### "ANTHROPIC_API_KEY" error

Set in `.env`:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run mva chat
```

Or set in config:

```yaml
# Note: Usually set via environment variable
```

### Logs not showing

Set in config.yml:

```yaml
log_level: DEBUG
log_stdout: true
```

## FAQ

**Q: Can I use my own LLM?**
A: Yes! Implement `BaseLLMClient` and pass it to `Agent()`. See [ARCHITECTURE.md](ARCHITECTURE.md).

**Q: Is the sandbox secure?**
A: It prevents path escapes but not all attacks. See [ARCHITECTURE.md](ARCHITECTURE.md) security section.

**Q: Can I combine skills and tools?**
A: Yes! Skills guide the agent to use specific tools. See [SKILLS.md](SKILLS.md).

**Q: How do I debug tool failures?**
A: Set `log_level: DEBUG` in config.yml. See [CONFIGURATION.md](CONFIGURATION.md).

**Q: Can I customize the system prompt?**
A: Yes! Use `system_prompt` in config.yml. See [CONFIGURATION.md](CONFIGURATION.md).

## Contributing

To improve documentation:

1. Edit the relevant `.md` file in `docs/`
2. Test your changes
3. Keep examples runnable
4. Cross-reference related docs

## Resources

- **CLAUDE.md** — Project notes and architecture details
- **README.md** — Main project README
- **pyproject.toml** — Dependencies and package config

## Versioning

This documentation matches **MVA latest** on the `main` branch.

For version-specific docs, check `git tag`.

## License

See LICENSE file in repository root.

---

**Ready to get started?** → [QUICKSTART.md](QUICKSTART.md)

**Questions?** Check the [FAQ](#faq) or review the relevant guide above.

**Found a bug?** Create an issue with details about your configuration and the error message.

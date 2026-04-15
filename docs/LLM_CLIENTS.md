# LLM Client Support

MVA supports multiple LLM backends with a unified interface. Choose your preferred provider by setting environment variables.

## Supported Providers

### OpenAI-Compatible (Default)
For local and remote OpenAI-compatible APIs: **vLLM**, **Ollama**, **LocalAI**, **LM Studio**, etc.

```bash
# .env
LLM_BASE_URL=http://127.0.0.1:8002/v1
DEFAULT_MODEL=gemma-4-4B-abliterated
LLM_API_KEY=no-key  # or your API key
```

**Models**: Any model supported by your server

---

### Anthropic Claude API
Access Claude models via Anthropic's hosted API.

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_MODEL=claude-3-5-sonnet-20241022
```

**Available Models**:
- `claude-3-5-sonnet-20241022` (recommended)
- `claude-3-5-haiku-20241022` (faster, smaller)
- `claude-3-opus-20250219` (most capable)

---

## How It Works

The `get_client()` factory uses this selection order:

1. **Explicit selection**: `LLM_PROVIDER` environment variable (if set)
2. **Auto-detection** (fallback): Based on API keys
   - If `ANTHROPIC_API_KEY` is set → AnthropicClient
   - Otherwise → OpenAIClient (default)

```python
from mva.utils.llm_client import get_client

client = get_client()  # Uses LLM_PROVIDER or auto-detects
```

## Architecture

### Base Class: `BaseLLMClient`
Abstract interface that all clients implement:
- `complete_stream()` — Streaming responses
- `complete()` — Non-streaming text completion
- `chat()` — Non-streaming with tool support
- `ls_models()` — List available models

### OpenAIClient
Direct implementation for OpenAI-compatible APIs. No format conversion needed.

### AnthropicClient
Implements `BaseLLMClient` with Anthropic API. Automatically:
- **Converts messages** from OpenAI format to Anthropic format
- **Converts tools** from OpenAI function calling to Anthropic tool_use
- **Converts responses** back to OpenAI format

This means the rest of MVA code works unchanged regardless of which backend you use.

---

## Explicit Provider Selection

Set `LLM_PROVIDER` to explicitly choose your backend:

```bash
# Use OpenAI-compatible (vLLM, Ollama, etc.)
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:8002/v1
DEFAULT_MODEL=llama-2-7b

# Or use Anthropic
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_MODEL=claude-3-5-sonnet-20241022
```

**Supported values:**
- `openai` — OpenAI-compatible API (vLLM, Ollama, LocalAI, etc.)
- `anthropic` — Anthropic Claude API
- `ollama` — Alias for openai (Ollama compatibility)
- `vllm` — Alias for openai (vLLM compatibility)
- `localai` — Alias for openai (LocalAI compatibility)
- `auto` — Auto-detect based on API keys (default if not set)

---

## Message Format Conversion

### OpenAI Format (Native)
```json
{
  "role": "user",
  "content": "Hello"
}
```

### Anthropic Format
```json
{
  "role": "user",
  "content": "Hello"
}
```

The `AnthropicClient` handles conversion automatically. System prompts are extracted and passed as the `system` parameter.

---

## Tool Calling

Both clients support tool calling with automatic format conversion:

### OpenAI Format (Native)
```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "arguments": "{\"filename\": \"test.txt\"}"
  }
}
```

### Anthropic Format
```json
{
  "type": "tool_use",
  "id": "...",
  "name": "read_file",
  "input": {"filename": "test.txt"}
}
```

The `AnthropicClient` converts between these formats automatically.

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `auto` | Explicitly select provider: `openai`, `anthropic`, `ollama`, `vllm`, `localai`, or `auto` |
| `LLM_BASE_URL` | `http://127.0.0.1:8001/v1` | OpenAI-compatible server endpoint |
| `DEFAULT_MODEL` | `model` | Model to use when not specified |
| `LLM_API_KEY` | `no-key` | API key for OpenAI-compatible servers |
| `ANTHROPIC_API_KEY` | (none) | Anthropic API key |
| `SANDBOX_DIR` | `/tmp/agent_workspace` | Directory for sandboxed code execution |

---

## Switching Providers

Just change `LLM_PROVIDER`:

**From OpenAI-compatible to Anthropic:**
```bash
# Before: .env
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:8002/v1
DEFAULT_MODEL=llama-2-7b
LLM_API_KEY=no-key

# After: .env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_MODEL=claude-3-5-sonnet-20241022
```

**Or back to OpenAI-compatible:**
```bash
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:8002/v1
DEFAULT_MODEL=llama-2-7b
LLM_API_KEY=no-key
```

No code changes needed! The agent automatically uses the selected provider.

---

## Logging

Both clients log their initialization and selection:

**Explicit OpenAI-compatible selection:**
```
INFO     private_notebook.llm: Initialized OpenAIClient with base_url=http://127.0.0.1:8002/v1
INFO     private_notebook.llm: get_client: using OpenAIClient (LLM_PROVIDER=openai)
```

**Explicit Anthropic selection:**
```
INFO     private_notebook.llm: Initialized AnthropicClient with Anthropic API
INFO     private_notebook.llm: get_client: using AnthropicClient (LLM_PROVIDER=anthropic)
```

**Auto-detection (fallback):**
```
INFO     private_notebook.llm: get_client: using AnthropicClient (auto-detected from ANTHROPIC_API_KEY)
INFO     private_notebook.llm: get_client: using OpenAIClient (default)
```

Set `log_level: DEBUG` in `config.yml` to see detailed API traffic.

---

## Error Handling

Both clients raise `LLMError` with HTTP status codes:

```python
try:
    result = client.chat(messages, tools=tools)
except LLMError as e:
    print(f"API error {e.status_code}: {e}")
```

Status codes:
- `400`/`422` — Invalid request (bad tools, bad format)
- `401` — Authentication failed (bad API key)
- `429` — Rate limited
- `500+` — Server error

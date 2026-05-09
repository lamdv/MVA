# Model YAML Configuration Format

MVA uses `model.yaml` to configure LLM providers. This replaces the old `.env`/environment-variable approach.

## Search Order

MVA looks for `model.yaml` in this order (first match wins):

1. **`./.mva/model.yaml`** — project-level config (recommended)
2. **`~/.config/mva/model.yaml`** — user-level global config
3. **Environment variables** — legacy fallback (see below)

## Full Format

```yaml
# Active provider key (must match a key in `providers`)
provider: openai

providers:
  # -- OpenAI-compatible API (vLLM, Ollama, LocalAI, etc.) --
  openai:
    type: openai
    base_url: http://127.0.0.1:8002/v1
    api_key: no-key
    default_model: gemma-4-4B-abliterated
    timeout: 120

  # -- Anthropic Claude API --
  anthropic:
    type: anthropic
    base_url: https://api.anthropic.com/v1
    api_key: sk-ant-...
    default_model: claude-3-5-sonnet-20241022
    timeout: 120

  # -- Ollama (uses OpenAI-compatible API) --
  ollama:
    type: openai
    base_url: http://localhost:11434/v1
    api_key: no-key
    default_model: llama3.2
    timeout: 120

# Directory for sandboxed file operations
sandbox_dir: ./sandbox
```

## Field Reference

### Top-Level

| Field | Required | Default | Description |
|:---|:---:|:---|:---|
| `provider` | Yes | `openai` | Key into `providers` dict; selects the active provider. |
| `providers` | Yes | `{openai: {}}` | Map of provider names to configs. |
| `sandbox_dir` | No | `./sandbox` | Directory for sandboxed file operations. |

### Provider Config

| Field | Required | Default | Description |
|:---|:---:|:---|:---|
| `type` | No | `openai` | Provider type. `"openai"` for OpenAI-compatible API. |
| `base_url` | No | `http://127.0.0.1:8002/v1` | API endpoint URL. |
| `api_key` | No | `no-key` | API key. Use `"no-key"` for local servers. |
| `default_model` | No | `""` | Default model name sent to the server. |
| `timeout` | No | `120` | Request timeout in seconds. |

## Switching Providers

To switch between providers, change the `provider` key:

```yaml
# Switch to Anthropic
provider: anthropic
```

The active provider's configuration is resolved via `config.get_active_provider()`.

## Legacy Environment Variable Fallback

If no `model.yaml` is found, MVA falls back to these environment variables:

| Variable | Default | Equivalent YAML field |
|:---|:---|:---|
| `LLM_PROVIDER` | `openai` | `provider` |
| `LLM_BASE_URL` | `http://127.0.0.1:8002/v1` | `providers.<name>.base_url` |
| `LLM_API_KEY` | `no-key` | `providers.<name>.api_key` |
| `DEFAULT_MODEL` | `""` | `providers.<name>.default_model` |
| `LLM_TIMEOUT` | `120` | `providers.<name>.timeout` |
| `SANDBOX_DIR` | `./sandbox` | `sandbox_dir` |

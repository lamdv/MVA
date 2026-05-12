# Provider Integration Guide

MVA supports any LLM provider with an OpenAI-compatible API out of the box, plus native Anthropic support. This guide covers how to configure popular providers.

All configuration goes in `model.yaml` (see [`model_yaml_format.md`](model_yaml_format.md) for the full schema). The old `.env` / environment-variable approach still works as a fallback but is **not recommended**.

---

## Table of Contents

- [OpenAI-Compatible Providers](#openai-compatible-providers)
- [DeepSeek](#deepseek)
- [Kimi (Moonshot)](#kimi-moonshot)
- [OpenRouter](#openrouter)
- [Anthropic Claude](#anthropic-claude)
- [Switching Providers](#switching-providers)
- [Troubleshooting](#troubleshooting)

---

## OpenAI-Compatible Providers

Any provider serving an OpenAI-compatible API uses `type: openai`. This covers **DeepSeek**, **Kimi**, **OpenRouter**, **Ollama**, **vLLM**, **LocalAI**, **Groq**, **Together AI**, and many more.

The common pattern is:

```yaml
provider: <active_provider_key>

providers:
  <provider_key>:
    type: openai
    base_url: <api_base_url>
    api_key: <your_api_key>
    default_model: <model_name>
    timeout: 120  # optional, default 120
```

Place `model.yaml` in:
- **`./.mva/model.yaml`** — project-level (recommended)
- **`~/.config/mva/model.yaml`** — user-level global fallback

---

## DeepSeek

**API docs:** [platform.deepseek.com](https://platform.deepseek.com/)

| Field | Value |
|:---|---|
| `base_url` | `https://api.deepseek.com` |
| `default_model` | `deepseek-chat` or `deepseek-reasoner` |

### Configuration

```yaml
provider: deepseek

providers:
  deepseek:
    type: openai
    base_url: https://api.deepseek.com
    api_key: sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    default_model: deepseek-chat
    timeout: 120
```

### Supported Models

| Model | Description |
|:---|---|
| `deepseek-chat` | Optimized for general-purpose tasks and tool calling. |
| `deepseek-reasoner` | Optimized for complex reasoning. MVA captures and displays `reasoning_content` from this model in the terminal UI. |

> **Note:** `deepseek-reasoner` may have limited or no tool-calling support — test with simple `/tools` commands first.

### Legacy Environment Variable Setup

If you don't have a `model.yaml`, MVA falls back to these environment variables:

| Variable | Value | Description |
| :--- | :--- | :--- |
| `LLM_BASE_URL` | `https://api.deepseek.com` | The base URL for DeepSeek's API. |
| `LLM_API_KEY` | `your_deepseek_api_key` | Your actual DeepSeek API key. |
| `DEFAULT_MODEL` | `deepseek-chat` | The model to use (e.g., `deepseek-chat` or `deepseek-reasoner`). |

```env
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEFAULT_MODEL=deepseek-chat
```

---



## Kimi (Moonshot)

**API docs:** [platform.moonshot.cn](https://platform.moonshot.cn/docs)

| Field | Value |
|:---|---|
| `base_url` | `https://api.moonshot.cn/v1` |
| `default_model` | e.g. `moonshot-v1-8k`, `moonshot-v1-32k`, `moonshot-v1-128k` |

### Configuration

```yaml
provider: kimi

providers:
  kimi:
    type: openai
    base_url: https://api.moonshot.cn/v1
    api_key: sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    default_model: moonshot-v1-128k
    timeout: 120
```

### Notes

- Kimi models have large context windows (up to 128k tokens), making them well-suited for codebase analysis and long conversations.
- Tool/function calling is supported on `moonshot-v1` series.
- The API base URL **must** end with `/v1`.

---

## OpenRouter

**API docs:** [openrouter.ai/docs](https://openrouter.ai/docs)

OpenRouter is a unified API gateway that provides access to many models from different providers. It is fully OpenAI-compatible.

| Field | Value |
|:---|---|
| `base_url` | `https://openrouter.ai/api/v1` |
| `default_model` | Any model slug from OpenRouter, e.g. `openai/gpt-4o`, `anthropic/claude-3.5-sonnet`, `google/gemini-2.0-flash` |

### Configuration

```yaml
provider: openrouter

providers:
  openrouter:
    type: openai
    base_url: https://openrouter.ai/api/v1
    api_key: sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    default_model: openai/gpt-4o
    timeout: 120
```

### OpenRouter-Specific Headers

MVA does not set OpenRouter-specific HTTP headers by default, but you can pass them via the `extra_headers` field (requires extending the config schema if not yet supported). Common headers include:

| Header | Purpose |
|:---|---|
| `HTTP-Referer` | Your site URL for rankings on openrouter.ai |
| `X-Title` | App name for rankings on openrouter.ai |

### Notes

- OpenRouter supports **model fallbacks** — MVA sends the model name as-is, and OpenRouter handles fallback if you configure it on their dashboard.
- Tool calling works with most models, but verify individual model support on OpenRouter's model page.
- API key starts with `sk-or-v1-`.

---

## Anthropic Claude

**API docs:** [docs.anthropic.com](https://docs.anthropic.com/en/docs)

Anthropic uses a **native** (non-OpenAI-compatible) API, so MVA has a dedicated `type: anthropic` provider.

| Field | Value |
|:---|---|
| `base_url` | `https://api.anthropic.com/v1` |
| `default_model` | e.g. `claude-3-5-sonnet-20241022`, `claude-3-5-haiku-20241022`, `claude-opus-4-20250514` |

### Configuration

```yaml
provider: anthropic

providers:
  anthropic:
    type: anthropic
    base_url: https://api.anthropic.com/v1
    api_key: sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    default_model: claude-3-5-sonnet-20241022
    timeout: 120
```

### Supported Models

| Model | Description |
|:---|---|
| `claude-3-5-sonnet-20241022` | Best balance of speed, cost, and capability. Strong tool caller. |
| `claude-3-5-haiku-20241022` | Faster, cheaper; good for simple tasks. |
| `claude-opus-4-20250514` | Most capable, but slower and more expensive. |

### Notes

- Anthropic supports **extended thinking** — MVA will capture and display thinking blocks if the model returns them.
- Tool calling is supported natively via Anthropic's tool-use API.
- API key starts with `sk-ant-`.

---

## VS Code as an LLM Server (Copilot Proxy)

Several VS Code extensions can expose GitHub Copilot's language models through an OpenAI-compatible API, letting MVA (or any tool) use your Copilot subscription outside of VS Code.

---

### LM Proxy

**GitHub:** [ryonakae/vscode-lm-proxy](https://github.com/ryonakae/vscode-lm-proxy)
**VS Code Marketplace:** [LM Proxy](https://marketplace.visualstudio.com/items?itemName=ryonakae.vscode-lm-proxy)

[LM Proxy](https://github.com/ryonakae/vscode-lm-proxy) is a VS Code extension that exposes GitHub Copilot's language models through OpenAI and Anthropic compatible REST APIs. It uses the VS Code Language Model API (LM API) to communicate with Copilot.

#### Prerequisites

- A valid GitHub Copilot subscription (any plan, including free tier)
- VS Code installed

#### Configuration

1. Install the **LM Proxy** extension from the VS Code marketplace.
2. Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and run `LM Proxy: Start LM Proxy Server`.
3. The server starts on `http://localhost:4000` by default (configurable via `vscode-lm-proxy.port` setting).

MVA configuration:

```yaml
provider: copilot-proxy

providers:
  copilot-proxy:
    type: openai
    base_url: http://127.0.0.1:4000/openai/v1
    api_key: no-key  # LM Proxy doesn't require an API key
    default_model: vscode-lm-proxy
    timeout: 120
```

> **Note:** Set `default_model` to `vscode-lm-proxy` to use the model selected in the extension settings, or use a specific model name like `gpt-4.1` or `claude-3.5-sonnet`.

#### Available Endpoints

| Endpoint | Description |
|:---|---|
| `POST /openai/v1/chat/completions` | OpenAI-compatible chat completions (streaming supported) |
| `GET /openai/v1/models` | List available models |

---

### Copilot Chat OpenAI Proxy

**GitHub:** [AmadeusITGroup/copilot-chat-openai-proxy](https://github.com/AmadeusITGroup/copilot-chat-openai-proxy)
**VS Code Marketplace:** [Chat Participant OpenAI Proxy](https://marketplace.visualstudio.com/items?itemName=amadeus-it.copilot-chat-openai-proxy)

An alternative extension that creates a local proxy server routing OpenAI API requests through GitHub Copilot's language models.

#### Prerequisites

- A valid GitHub Copilot subscription (any plan, including free tier)
- VS Code installed

#### Configuration

1. Install the **Chat Participant OpenAI Proxy** extension.
2. Open VS Code and run the command `@llmproxy /start` to start the proxy server.
3. The server listens on `http://localhost:8080` by default.

MVA configuration:

```yaml
provider: copilot-proxy-alt

providers:
  copilot-proxy-alt:
    type: openai
    base_url: http://127.0.0.1:8080/v1
    api_key: no-key
    default_model: gpt-4o
    timeout: 120
```

#### Notes

- Supports `response_format: { type: "json_schema", ... }` for structured outputs.
- The model name passed as `default_model` is mostly cosmetic — the proxy uses whatever Copilot model is available.
- Swagger UI available at `http://localhost:8080/api-docs`.

---

## Switching Providers

To switch between configured providers, change the top-level `provider` key:

```yaml
provider: deepseek   # switch to DeepSeek
# provider: kimi     # or Kimi
# provider: openrouter  # or OpenRouter
# provider: anthropic   # or Anthropic
```

MVA resolves the active configuration via `config.get_active_provider()`. You can have multiple providers defined and toggle between them with a single YAML change — no restart needed if MVA reloads config on each turn (check current behavior).

---

## Troubleshooting

### Connection Errors

- Ensure `base_url` does **not** end with `/chat/completions` — it should be the base URL only (e.g. `https://api.deepseek.com`, not `https://api.deepseek.com/chat/completions`).
- For OpenAI-compatible providers, ensure the URL ends with `/v1` where applicable (Kimi, OpenRouter).
- Verify your API key is valid and has sufficient credits/quota.
- Check network connectivity — the provider's API may be blocked by a firewall.

### Tool Calling Issues

Not all models support tool/function calling well. If a model fails to invoke tools:

1. Run `/tools` in the REPL to verify tools are registered.
2. Try a different model known for good tool calling (e.g. `deepseek-chat`, `claude-3-5-sonnet`, `gpt-4o`).
3. Check the provider's documentation for model-specific tool-calling limitations.

### Streaming Issues

- If the UI stutters or freezes during streaming, try increasing `timeout` in the provider config.
- Some providers have rate limits — space out requests or upgrade your plan.

### Authentication Errors

- For **OpenAI-compatible**: set `api_key` to `"no-key"` for local servers (vLLM, Ollama) that don't require auth.
- For **Anthropic**: ensure the API key starts with `sk-ant-`.
- For **OpenRouter**: ensure the API key starts with `sk-or-v1-`.
- For **Kimi**: ensure the API key starts with `sk-`.

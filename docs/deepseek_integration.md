# Integrating DeepSeek with MVA

MVA uses an OpenAI-compatible client, which means you can easily integrate DeepSeek by configuring the environment variables.

## Prerequisites

1. Obtain a DeepSeek API Key from the [DeepSeek Platform](https://platform.deepseek.com/).

## Configuration

You can configure MVA to use DeepSeek by updating your `.env` file in the project root.

Set the following environment variables:

| Variable | Value | Description |
| :--- | :--- | :--- |
| `LLM_BASE_URL` | `https://api.deepseek.com` | The base URL for DeepSeek's API. |
| `LLM_API_KEY` | `your_deepseek_api_key` | Your actual DeepSeek API key. |
| `DEFAULT_MODEL` | `deepseek-chat` | The model to use (e.g., `deepseek-chat` or `deepseek-reasoner`). |

### Example `.env`

```env
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEFAULT_MODEL=deepseek-chat
```

## Supported Models

MVA supports both standard and reasoning models provided by DeepSeek:

- **`deepseek-chat`**: Optimized for general purpose tasks and tool calling.
- **`deepseek-reasoner`**: Optimized for complex reasoning tasks. MVA is designed to capture and display the `reasoning_content` from this model in the terminal UI.

## Troubleshooting

If you encounter connection errors, ensure that:
- Your `LLM_BASE_URL` does **not** end with `/chat/completions`.
- Your API key is valid and has sufficient credits.
- Your network allows outgoing requests to `api.deepseek.com`.

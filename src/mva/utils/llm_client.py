import json
import os
from abc import ABC, abstractmethod

import requests
from dotenv import load_dotenv

from mva.utils.log import get_logger

load_dotenv()

_log = get_logger("llm")


class LLMError(RuntimeError):
    """HTTP-level error from the inference server."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self):
        self.default_model = os.getenv("DEFAULT_MODEL", "model")

    @abstractmethod
    def complete_stream(
        self, messages, model=None, temperature=0.7, max_tokens=None, tools=None, tool_choice="auto"
    ):
        """Stream a chat-completion response."""
        pass

    @abstractmethod
    def complete(self, messages, model=None, temperature=0.7, max_tokens=None) -> str:
        """Non-streaming chat completion."""
        pass

    @abstractmethod
    def chat(
        self, messages, model=None, temperature=0.7, max_tokens=None, tools=None, tool_choice="auto"
    ) -> dict:
        """Non-streaming call with tool support."""
        pass

    @abstractmethod
    def ls_models(self):
        """List available models."""
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI-compatible API client (vLLM, Ollama, etc.)."""

    def __init__(self):
        super().__init__()
        self.base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8001/v1")
        _log.info("Initialized OpenAIClient with base_url=%s", self.base_url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self, accept_stream: bool = False) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'no-key')}",
        }
        if accept_stream:
            headers["Accept"] = "text/event-stream"
        return headers

    def _base_payload(
        self,
        messages: list,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        tools: list | None = None,
        tool_choice: str = "auto",
    ) -> dict:
        payload: dict = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": float(temperature),
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        return payload

    @staticmethod
    def _extract_error(response: requests.Response) -> str:
        try:
            return response.json().get("error", {}).get("message", response.text)
        except Exception:
            return response.text

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete_stream(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=None,
        tools=None,
        tool_choice="auto",
    ):
        """Stream a chat-completion response.

        Yields:
            ``{"type": "content"|"reasoning"|"error", "content": str}``
            ``{"type": "tool_call_delta", "index": int, "id": str,
               "function": {"name": str, "arguments": str}}``
            (tool_call_delta chunks only when *tools* is provided)
        """
        payload = {
            **self._base_payload(messages, model, temperature, max_tokens, tools, tool_choice),
            "stream": True,
        }

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(accept_stream=True),
                stream=True,
                timeout=(10, 600),
            )

            if response.status_code != 200:
                detail = self._extract_error(response)
                msg = f"Error {response.status_code}: {detail}"
                _log.error("stream HTTP %d: %s", response.status_code, detail)
                if tools is not None and response.status_code in (400, 422):
                    raise LLMError(msg, status_code=response.status_code)
                yield {"type": "error", "content": msg}
                return

            for line in response.iter_lines():
                if not line:
                    continue

                decoded = line.decode("utf-8").strip()

                if decoded.startswith("data: "):
                    data_str = decoded[6:].strip()
                elif decoded.startswith("data:"):
                    data_str = decoded[5:].strip()
                else:
                    continue

                if data_str == "[DONE]":
                    return

                try:
                    data = json.loads(data_str)
                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    if delta.get("reasoning_content"):
                        yield {"type": "reasoning", "content": delta["reasoning_content"]}

                    if delta.get("content"):
                        yield {"type": "content", "content": delta["content"]}

                    for tc in delta.get("tool_calls", []):
                        yield {
                            "type": "tool_call_delta",
                            "index": tc.get("index", 0),
                            "id": tc.get("id", ""),
                            "function": tc.get("function", {}),
                        }

                except json.JSONDecodeError:
                    continue

        except LLMError:
            raise
        except Exception as e:
            _log.error("stream network error: %s", e)
            yield {"type": "error", "content": str(e)}

    def complete(self, messages, model=None, temperature=0.7, max_tokens=None) -> str:
        """Non-streaming chat completion. Returns full content string."""
        full_content = []
        for chunk in self.complete_stream(
            messages, model=model, temperature=temperature, max_tokens=max_tokens
        ):
            if chunk["type"] == "content":
                full_content.append(chunk["content"])
            elif chunk["type"] == "error":
                raise RuntimeError(chunk["content"])
        return "".join(full_content)

    def chat(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=None,
        tools=None,
        tool_choice="auto",
    ) -> dict:
        """Non-streaming call; returns the full ``choices[0].message`` dict."""
        payload = self._base_payload(
            messages, model, temperature, max_tokens, tools, tool_choice
        )
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=(10, 120),
            )
            if response.status_code != 200:
                detail = self._extract_error(response)
                _log.error("chat HTTP %d: %s", response.status_code, detail)
                raise LLMError(
                    f"Error {response.status_code}: {detail}",
                    status_code=response.status_code,
                )
            return response.json()["choices"][0]["message"]
        except LLMError:
            raise
        except Exception as e:
            _log.error("chat network error: %s", e)
            raise LLMError(str(e)) from e

    def ls_models(self):
        url = f"{self.base_url}/models"
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                return response.json()
            _log.warning("ls_models HTTP %d", response.status_code)
        except Exception as e:
            _log.error("ls_models network error: %s", e)
        return []


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API client."""

    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required for Anthropic API")
        self.base_url = "https://api.anthropic.com/v1"
        _log.info("Initialized AnthropicClient with Anthropic API")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

    def _convert_tools(self, tools: list | None) -> list | None:
        """Convert OpenAI-style tools to Anthropic format."""
        if not tools:
            return None

        anthropic_tools = []
        for tool in tools:
            func = tool.get("function", {})
            anthropic_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return anthropic_tools

    def _convert_messages_to_anthropic(self, messages: list) -> tuple[str | None, list]:
        """Convert OpenAI-style messages to Anthropic format.

        Returns (system_prompt, converted_messages)
        """
        system_prompt = None
        converted = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                system_prompt = content
            elif role == "assistant":
                # Handle tool calls in assistant messages
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    # Convert to Anthropic's tool_use format
                    converted_content = []
                    if content:
                        converted_content.append({"type": "text", "text": content})

                    for tc in tool_calls:
                        func = tc.get("function", {})
                        try:
                            input_data = json.loads(func.get("arguments", "{}"))
                        except Exception:
                            input_data = {}

                        converted_content.append({
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": func.get("name", ""),
                            "input": input_data,
                        })

                    converted.append({"role": "assistant", "content": converted_content})
                else:
                    converted.append({"role": "assistant", "content": content or ""})

            elif role == "tool":
                # Convert tool results
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
            elif role == "user":
                converted.append({"role": "user", "content": content or ""})

        return system_prompt, converted

    def _convert_response_to_openai(self, response_data: dict) -> dict:
        """Convert Anthropic response to OpenAI-compatible format."""
        content = response_data.get("content", [])
        text_content = ""
        tool_calls = []

        for block in content:
            if block.get("type") == "text":
                text_content = block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        result = {"role": "assistant", "content": text_content}
        if tool_calls:
            result["tool_calls"] = tool_calls
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete_stream(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=None,
        tools=None,
        tool_choice="auto",
    ):
        """Stream a chat-completion response.

        Yields same format as OpenAI client for compatibility.
        """
        system_prompt, converted_messages = self._convert_messages_to_anthropic(messages)
        anthropic_tools = self._convert_tools(tools)

        payload = {
            "model": model or self.default_model,
            "messages": converted_messages,
            "temperature": float(temperature),
            "stream": True,
        }

        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if system_prompt:
            payload["system"] = system_prompt
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        try:
            response = requests.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(),
                stream=True,
                timeout=(10, 600),
            )

            if response.status_code != 200:
                msg = f"Error {response.status_code}: {response.text}"
                _log.error("stream HTTP %d: %s", response.status_code, response.text)
                if tools is not None and response.status_code in (400, 422):
                    raise LLMError(msg, status_code=response.status_code)
                yield {"type": "error", "content": msg}
                return

            for line in response.iter_lines():
                if not line:
                    continue

                decoded = line.decode("utf-8").strip()
                if not decoded.startswith("data: "):
                    continue

                data_str = decoded[6:].strip()
                if data_str == "[DONE]":
                    continue

                try:
                    data = json.loads(data_str)
                    delta = data.get("delta", {})

                    # Text content
                    if delta.get("type") == "text_delta":
                        yield {"type": "content", "content": delta.get("text", "")}

                except json.JSONDecodeError:
                    continue

        except LLMError:
            raise
        except Exception as e:
            _log.error("stream network error: %s", e)
            yield {"type": "error", "content": str(e)}

    def complete(self, messages, model=None, temperature=0.7, max_tokens=None) -> str:
        """Non-streaming chat completion."""
        system_prompt, converted_messages = self._convert_messages_to_anthropic(messages)

        payload = {
            "model": model or self.default_model,
            "messages": converted_messages,
            "temperature": float(temperature),
        }

        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if system_prompt:
            payload["system"] = system_prompt

        try:
            response = requests.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(),
                timeout=(10, 120),
            )

            if response.status_code != 200:
                _log.error("complete HTTP %d: %s", response.status_code, response.text)
                raise LLMError(
                    f"Error {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )

            result = response.json()
            content = result.get("content", [])
            text_parts = [block.get("text", "") for block in content if block.get("type") == "text"]
            return "".join(text_parts)

        except LLMError:
            raise
        except Exception as e:
            _log.error("complete network error: %s", e)
            raise LLMError(str(e)) from e

    def chat(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=None,
        tools=None,
        tool_choice="auto",
    ) -> dict:
        """Non-streaming call with tool support."""
        system_prompt, converted_messages = self._convert_messages_to_anthropic(messages)
        anthropic_tools = self._convert_tools(tools)

        payload = {
            "model": model or self.default_model,
            "messages": converted_messages,
            "temperature": float(temperature),
        }

        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if system_prompt:
            payload["system"] = system_prompt
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        try:
            response = requests.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(),
                timeout=(10, 120),
            )

            if response.status_code != 200:
                _log.error("chat HTTP %d: %s", response.status_code, response.text)
                raise LLMError(
                    f"Error {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )

            result = response.json()
            return self._convert_response_to_openai(result)

        except LLMError:
            raise
        except Exception as e:
            _log.error("chat network error: %s", e)
            raise LLMError(str(e)) from e

    def ls_models(self):
        """List available Anthropic models."""
        # Anthropic doesn't provide a models endpoint, return known models
        return {
            "models": [
                {"id": "claude-3-5-sonnet-20241022"},
                {"id": "claude-3-5-haiku-20241022"},
                {"id": "claude-3-opus-20250219"},
            ]
        }


# Backward compatibility alias
LlamaClient = OpenAIClient


def get_client() -> BaseLLMClient:
    """Factory function to get the appropriate LLM client.

    Selects client type from LLM_PROVIDER env var:
    - "anthropic" → AnthropicClient
    - "openai" or "ollama" (default) → OpenAIClient

    Falls back to auto-detection if LLM_PROVIDER not set:
    - If ANTHROPIC_API_KEY is set → AnthropicClient
    - Otherwise → OpenAIClient
    """
    provider = os.getenv("LLM_PROVIDER", "").lower().strip()

    # Explicit provider selection
    if provider == "anthropic":
        _log.info("get_client: using AnthropicClient (LLM_PROVIDER=anthropic)")
        return AnthropicClient()
    elif provider in ("openai", "ollama", "vllm", "localai"):
        _log.info("get_client: using OpenAIClient (LLM_PROVIDER=%s)", provider)
        return OpenAIClient()
    elif provider and provider != "auto":
        _log.warning("get_client: unknown LLM_PROVIDER=%s, falling back to auto-detection", provider)

    # Auto-detection (fallback)
    if os.getenv("ANTHROPIC_API_KEY"):
        _log.info("get_client: using AnthropicClient (auto-detected from ANTHROPIC_API_KEY)")
        return AnthropicClient()
    else:
        _log.info("get_client: using OpenAIClient (default)")
        return OpenAIClient()

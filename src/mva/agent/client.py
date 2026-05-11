"""OpenAI-compatible LLM chat completion client with tool calling."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Generator

import requests

from mva.config import ConfigError, load_config
from mva.agent.tools import ToolDef


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class ChatMessage:
    """A single message in a chat conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | list[dict[str, Any]]
    tool_call_id: str | None = None  # for tool role
    tool_calls: list[dict[str, Any]] | None = None  # for assistant role
    reasoning_content: str | None = None  # DeepSeek thinking mode


@dataclass
class ChatChoice:
    """A single choice returned by the chat completions endpoint."""

    message: ChatMessage
    index: int = 0
    finish_reason: str | None = None
    logprobs: Any = None


@dataclass
class CompletionUsage:
    """Token usage information."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatResponse:
    """Full response from a v1/chat/completions call."""

    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[ChatChoice] = field(default_factory=list)
    usage: CompletionUsage | None = None
    raw: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LLMClient:
    """A client for sending chat completion requests to an OpenAI-compatible API.

    Configuration is resolved in the following priority order:

    1. Constructor arguments (``base_url``, ``api_key``, ``default_model``)
    2. ``model.yaml`` (see :mod:`mva.config` for discovery)
    3. Environment variables (legacy fallback — ``LLM_BASE_URL``,
       ``LLM_API_KEY``, ``DEFAULT_MODEL``)
    4. Hard-coded defaults
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout: int | None = None,  # seconds
    ) -> None:
        # Load from model.yaml (or env fallback)
        try:
            cfg = load_config()
            provider_cfg = cfg.providers.get(cfg.provider)
        except ConfigError:
            cfg = None
            provider_cfg = None

        self._config_cfg = cfg  # keep for runtime queries
        self.current_provider: str | None = (
            str(cfg.provider) if cfg else None
        )
        self._available_models: list[str] = (
            list(provider_cfg.models) if provider_cfg else []
        )
        self.base_url = (
            base_url
            or (provider_cfg and provider_cfg.base_url)
            or "http://127.0.0.1:8002/v1"
        ).rstrip("/")
        self.api_key = (
            api_key
            or (provider_cfg and provider_cfg.api_key)
            or "no-key"
        )
        self.default_model = (
            default_model
            or (provider_cfg and provider_cfg.default_model)
            or ""
        )
        self.timeout = (
            timeout
            or (provider_cfg and provider_cfg.timeout)
            or 120
        )

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    # -- Runtime reconfiguration -------------------------------------------

    def reconfigure(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        """Reconfigure the client at runtime (e.g. after provider switch).

        Parameters
        ----------
        base_url:
            New base URL. ``None`` leaves the current value unchanged.
        api_key:
            New API key. ``None`` leaves the current value unchanged.
        default_model:
            New default model. ``None`` leaves the current value unchanged.
        timeout:
            New timeout in seconds. ``None`` leaves the current value unchanged.
        """
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        if api_key is not None:
            self.api_key = api_key
            self._session.headers.update(
                {"Authorization": f"Bearer {self.api_key}"}
            )
        if default_model is not None:
            self.default_model = default_model
        if timeout is not None:
            self.timeout = timeout

    def switch_provider(self, provider_name: str) -> bool:
        """Switch to a different provider from the config file.

        Re-loads ``model.yaml`` and applies the named provider's
        configuration.  Returns ``True`` on success, ``False`` if the
        provider is not found.

        This is a convenience wrapper around :func:`reload_config` and
        :meth:`reconfigure`.

        The provider's ``models`` list (if any) is stored in
        *available_models* for UI discovery.
        """
        from mva.config import get_active_provider, reload_config  # noqa: PLC0415

        try:
            cfg = reload_config()
        except Exception:
            return False

        if provider_name not in cfg.providers:
            return False

        provider = cfg.providers[provider_name]
        self.reconfigure(
            base_url=provider.base_url,
            api_key=provider.api_key,
            default_model=provider.default_model,
            timeout=provider.timeout,
        )
        self.current_provider = provider_name
        self._available_models = list(provider.models)
        return True

    def set_model(self, model_name: str) -> bool:
        """Set the active model within the current provider.

        If *available_models* is non-empty, *model_name* must appear in
        that list.  When the list is empty, the model is set
        unconditionally (backward-compatible behaviour).

        Returns ``True`` on success.
        """
        if self._available_models and model_name not in self._available_models:
            return False
        self.default_model = model_name
        return True

    @property
    def available_models(self) -> list[str]:
        """Return the list of available model names for the current
        provider (may be empty if none were declared in config)."""
        return list(self._available_models)

    # -- Public API ---------------------------------------------------------

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        max_tokens: int = -1,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: str | list[str] | None = None,
        logprobs: int | None = None,
        presence_penalty: float = 0.0,
        frequency_penalty: float = 0.0,
        seed: int | None = None,
        user: str | None = None,
        tools: list[ToolDef] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **extra_params: Any,
    ) -> ChatResponse:
        """Send a chat completion request to the OpenAI-compatible API.

        Parameters
        ----------
        messages:
            A list of :class:`ChatMessage` objects representing the
            conversation so far.
        model:
            Model identifier. Falls back to *default_model*.
        max_tokens:
            Maximum number of tokens to generate.
        temperature:
            Sampling temperature (0–2).
        top_p:
            Nucleus sampling probability mass.
        stop:
            Stop sequence(s).
        logprobs:
            Return log probabilities of top N tokens (per token position).
        presence_penalty, frequency_penalty:
            Penalty values (-2–2).
        seed:
            Deterministic seed (if supported by the backend).
        user:
            End-user identifier for tracking.
        tools:
            Optional list of :class:`ToolDef` objects the model may call.
        tool_choice:
            Controls how the model uses tools.
            ``"auto"`` (default), ``"none"``, ``"required"``, or
            ``{"type": "function", "function": {"name": "..."}}``.
        **extra_params:
            Any additional parameters forwarded verbatim to the API body.

        Returns
        -------
        A :class:`ChatResponse` with parsed choices and usage info.
        """
        model = model or self.default_model
        if not model:
            raise ValueError(
                "A model must be specified via argument or DEFAULT_MODEL env var."
            )

        url = f"{self.base_url}/chat/completions"

        body: dict[str, Any] = {
            "model": model,
            "messages": [_message_to_dict(m) for m in messages],
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty,
        }

        if max_tokens > 0:
            body["max_tokens"] = max_tokens
        if stop is not None:
            body["stop"] = stop
        if logprobs is not None:
            body["logprobs"] = logprobs
        if seed is not None:
            body["seed"] = seed
        if user is not None:
            body["user"] = user
        if tools:
            body["tools"] = [_tool_to_dict(t) for t in tools]
            body["tool_choice"] = tool_choice or "auto"

        body.update(extra_params)

        try:
            resp = self._session.post(url, json=body, timeout=self.timeout)
            if not resp.ok:
                detail = resp.text[:500] if resp.text else "(no body)"
                request_dump = json.dumps(body, indent=2, default=str)[:2000]
                raise LLMError(
                    f"Chat completion failed (HTTP {resp.status_code}): {detail}\n"
                    f"Request body:\n{request_dump}"
                )
            raw = resp.json()
        except requests.RequestException as exc:
            raise LLMError(f"Chat completion request failed: {exc}") from exc

        return self._parse_chat_response(raw)

    # -- Convenience helpers ------------------------------------------------

    def chat_simple(self, messages: list[ChatMessage], **kwargs: Any) -> str:
        """Send a chat completion and return just the generated text.

        Shortcut for single-choice, text-only responses.
        """
        response = self.chat(messages, **kwargs)
        if response.choices:
            return response.choices[0].message.content
        return ""

    # -- Streaming ----------------------------------------------------------

    def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        max_tokens: int = -1,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: str | list[str] | None = None,
        presence_penalty: float = 0.0,
        frequency_penalty: float = 0.0,
        seed: int | None = None,
        user: str | None = None,
        tools: list[ToolDef] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **extra_params: Any,
    ) -> Generator[StreamingDelta, None, None]:
        """Stream tokens from the chat completions API (SSE).

        Yields :class:`StreamingDelta` for each chunk as it arrives.
        The final chunk carries ``finish_reason`` and optionally ``usage``.

        Tool calls are accumulated across chunks and emitted as
        ``tool_call_delta`` events. Fully formed tool calls are available
        in the last delta's ``tool_calls`` list.

        Parameters are identical to :meth:`chat`.
        """
        model = model or self.default_model
        if not model:
            raise ValueError(
                "A model must be specified via argument or DEFAULT_MODEL env var."
            )

        # Lazy import to avoid circular dependency with mva.utils
        from mva.utils import is_cancel_requested  # noqa: PLC0415

        url = f"{self.base_url}/chat/completions"

        body: dict[str, Any] = {
            "model": model,
            "messages": [_message_to_dict(m) for m in messages],
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty,
            "stream": True,
        }

        if max_tokens > 0:
            body["max_tokens"] = max_tokens
        if stop is not None:
            body["stop"] = stop
        if seed is not None:
            body["seed"] = seed
        if user is not None:
            body["user"] = user
        if tools:
            body["tools"] = [_tool_to_dict(t) for t in tools]
            body["tool_choice"] = tool_choice or "auto"

        body.update(extra_params)

        acc_content = ""
        acc_thinking = ""
        tool_calls_by_idx: dict[int, dict[str, Any]] = {}
        resp = None
        cancelled = False

        try:
            resp = self._session.post(url, json=body, stream=True, timeout=self.timeout)
            if not resp.ok:
                detail = resp.text[:500] if resp.text else "(no body)"
                request_dump = json.dumps(body, indent=2, default=str)[:2000]
                raise LLMError(
                    f"Streaming request failed (HTTP {resp.status_code}): {detail}\n"
                    f"Request body:\n{request_dump}"
                )

            for raw_line in resp.iter_lines():
                if is_cancel_requested():
                    cancelled = True
                    break

                if not raw_line:
                    continue
                line = raw_line.decode("utf-8").strip()

                if not line.startswith("data: "):
                    continue

                payload = line[6:].strip()
                if payload == "[DONE]":
                    break

                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta_obj = choice.get("delta", {})
                delta = delta_obj.get("content", "")
                finish = choice.get("finish_reason")

                # --- Tool calls in delta ---
                tc_deltas_raw = delta_obj.get("tool_calls")
                if tc_deltas_raw:
                    for tc in tc_deltas_raw:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_by_idx:
                            tool_calls_by_idx[idx] = {
                                "id": tc.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": tc.get("function", {}).get("name", ""),
                                    "arguments": "",
                                },
                            }
                        entry = tool_calls_by_idx[idx]
                        if tc.get("id"):
                            entry["id"] = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            entry["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            entry["function"]["arguments"] += fn["arguments"]

                # Collect completed tool calls
                tool_calls: list[dict[str, Any]] = []
                for idx in sorted(tool_calls_by_idx.keys()):
                    entry = tool_calls_by_idx[idx]
                    args_str = entry["function"]["arguments"]
                    tool_calls.append(
                        {
                            "id": entry["id"],
                            "type": "function",
                            "function": {
                                "name": entry["function"]["name"],
                                "arguments": args_str,
                            },
                        }
                    )

                # --- Reasoning / thinking ---
                reasoning = (
                    delta_obj.get("reasoning_content")
                    or delta_obj.get("reasoning")
                    or ""
                )
                if reasoning:
                    acc_thinking += reasoning

                if delta:
                    acc_content += delta

                usage: CompletionUsage | None = None
                usage_raw = chunk.get("usage")
                if usage_raw:
                    usage = CompletionUsage(
                        prompt_tokens=usage_raw.get("prompt_tokens", 0),
                        completion_tokens=usage_raw.get("completion_tokens", 0),
                        total_tokens=usage_raw.get("total_tokens", 0),
                    )

                yield StreamingDelta(
                    id=chunk.get("id", ""),
                    model=chunk.get("model", ""),
                    delta=delta,
                    accumulated=acc_content,
                    thinking_delta=reasoning,
                    thinking=acc_thinking,
                    finish_reason=finish,
                    usage=usage,
                    tool_calls=tool_calls if tool_calls else None,
                    reasoning_content=acc_thinking if acc_thinking else None,
                )

        except requests.RequestException as exc:
            raise LLMError(f"Streaming request failed: {exc}") from exc
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass  # connection may already be torn down on cancel

        # Emit a cancellation marker so the caller can react gracefully
        if cancelled:
            yield StreamingDelta(
                finish_reason="cancelled",
                accumulated=acc_content,
                thinking=acc_thinking,
                reasoning_content=acc_thinking if acc_thinking else None,
                delta="",
                tool_calls=None,
            )

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _parse_chat_response(raw: dict[str, Any]) -> ChatResponse:
        choices = [
            ChatChoice(
                message=ChatMessage(
                    role=ch.get("message", {}).get("role", "assistant"),
                    content=ch.get("message", {}).get("content", "") or "",
                    tool_calls=ch.get("message", {}).get("tool_calls"),
                ),
                index=ch.get("index", 0),
                finish_reason=ch.get("finish_reason"),
                logprobs=ch.get("logprobs"),
            )
            for ch in raw.get("choices", [])
        ]

        usage_raw = raw.get("usage")
        usage: CompletionUsage | None = None
        if usage_raw:
            usage = CompletionUsage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
                total_tokens=usage_raw.get("total_tokens", 0),
            )

        return ChatResponse(
            id=raw.get("id", ""),
            object=raw.get("object", "chat.completion"),
            created=raw.get("created", 0),
            model=raw.get("model", ""),
            choices=choices,
            usage=usage,
            raw=raw,
        )

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()


# ---------------------------------------------------------------------------
# Streaming types
# ---------------------------------------------------------------------------


@dataclass
class StreamingDelta:
    """A single streaming chunk from a ``chat_stream()`` call."""

    id: str = ""
    model: str = ""
    delta: str = ""  # regular response text fragment in *this* chunk
    accumulated: str = ""  # full regular response text so far (no thinking)
    thinking_delta: str = ""  # thinking / reasoning text fragment in *this* chunk
    thinking: str = ""  # full thinking / reasoning text so far
    reasoning_content: str | None = None  # full reasoning to echo back (DeepSeek)
    finish_reason: str | None = None
    usage: CompletionUsage | None = None
    tool_calls: list[dict[str, Any]] | None = None  # accumulated tool calls


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _message_to_dict(m: ChatMessage) -> dict[str, Any]:
    """Convert a ChatMessage to the dict format expected by the API."""
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_call_id is not None:
        d["tool_call_id"] = m.tool_call_id
    if m.tool_calls is not None:
        d["tool_calls"] = m.tool_calls
    if m.reasoning_content is not None:
        d["reasoning_content"] = m.reasoning_content
    return d


def _tool_to_dict(t: ToolDef) -> dict[str, Any]:
    """Convert a ToolDef to the dict format expected by the API."""
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        },
    }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base exception for LLM client errors."""


# (no cleanup needed)

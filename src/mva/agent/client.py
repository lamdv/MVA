"""OpenAI-compatible LLM chat completion client — pure HTTP transport.

This module contains a minimal HTTP client for OpenAI-compatible chat
completion APIs.  It has **no knowledge of config files, provider
switching, or model management** — those belong in the session layer.

Usage::

    client = LLMClient(
        base_url="http://127.0.0.1:8002/v1",
        api_key="no-key",
        default_model="gpt-4o",
        timeout=120,
    )
    for delta in client.chat_stream(messages, tools=[...]):
        print(delta.delta)
"""

from __future__ import annotations

import json
from typing import Any, Generator

import requests

from mva.agent.types import (
    ChatMessage,
    ChatResponse,
    CompletionUsage,
    LLMError,
    StreamingDelta,
    message_to_dict,
    parse_chat_response,
    tool_to_dict,
)
from mva.agent.tools import ToolDef


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LLMClient:
    """A thin HTTP client for OpenAI-compatible chat completion APIs.

    This class is a **pure transport layer**: it builds HTTP requests,
    sends them, and parses responses.  It does **not** load configuration
    files, manage provider state, or track available models.

    Parameters
    ----------
    base_url:
        Base URL of the inference server
        (e.g. ``"http://127.0.0.1:8002/v1"``).
    api_key:
        API key.  Use ``"no-key"`` for local servers.
    default_model:
        Default model identifier sent to the server.
    timeout:
        Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8002/v1",
        api_key: str = "no-key",
        default_model: str = "",
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    # -- Factory helpers ----------------------------------------------------

    @classmethod
    def from_config(cls) -> LLMClient:
        """Construct an ``LLMClient`` from ``model.yaml`` (or env fallback).

        Loads the active provider's configuration via :func:`mva.config.load_config`
        and returns a client configured accordingly.

        This is the recommended way to create a client in production.
        Use the constructor directly for testing or custom setups.
        """
        from mva.config import load_config  # noqa: PLC0415

        cfg = load_config()
        provider_cfg = cfg.providers.get(cfg.provider)
        if provider_cfg is None:
            raise LLMError(
                f"Active provider {cfg.provider!r} not found in configuration."
            )
        return cls(
            base_url=provider_cfg.base_url,
            api_key=provider_cfg.api_key,
            default_model=provider_cfg.default_model,
            timeout=provider_cfg.timeout,
        )

    # -- Non-streaming chat -------------------------------------------------

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
        """Send a chat completion request (non-streaming).

        Parameters
        ----------
        messages:
            A list of :class:`ChatMessage` objects representing the
            conversation so far.
        model:
            Model identifier. Falls back to *default_model*.
        max_tokens:
            Maximum number of tokens to generate.  Use -1 or omit
            to let the server decide.
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
                "A model must be specified via argument or default_model."
            )

        url = f"{self.base_url}/chat/completions"

        body: dict[str, Any] = {
            "model": model,
            "messages": [message_to_dict(m) for m in messages],
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
            body["tools"] = [tool_to_dict(t.name, t.description, t.parameters) for t in tools]
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

        return parse_chat_response(raw)

    # -- Convenience helper -------------------------------------------------

    def chat_simple(self, messages: list[ChatMessage], **kwargs: Any) -> str:
        """Send a chat completion and return just the generated text.

        Shortcut for single-choice, text-only responses.
        """
        response = self.chat(messages, **kwargs)
        if response.choices:
            return response.choices[0].message.content
        return ""

    # -- Streaming chat -----------------------------------------------------

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

        Yields a :class:`StreamingDelta` for each SSE chunk as it
        arrives.  Tool calls are accumulated across chunks and the
        final delta carries the complete list.

        Parameters are identical to :meth:`chat`.
        """
        model = model or self.default_model
        if not model:
            raise ValueError(
                "A model must be specified via argument or default_model."
            )

        # Lazy import to avoid circular dependency with mva.utils
        from mva.utils import is_cancel_requested  # noqa: PLC0415

        url = f"{self.base_url}/chat/completions"

        body: dict[str, Any] = {
            "model": model,
            "messages": [message_to_dict(m) for m in messages],
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
            body["tools"] = [tool_to_dict(t.name, t.description, t.parameters) for t in tools]
            body["tool_choice"] = tool_choice or "auto"

        body.update(extra_params)

        acc_content = ""
        acc_thinking = ""
        tool_calls_by_idx: dict[int, dict[str, Any]] = {}
        resp = None
        cancelled = False

        try:
            resp = self._session.post(
                url, json=body, stream=True, timeout=self.timeout
            )
            if not resp.ok:
                detail = resp.text[:500] if resp.text else "(no body)"
                request_dump = json.dumps(body, indent=2, default=str)[:2000]
                raise LLMError(
                    f"Streaming request failed (HTTP {resp.status_code}):"
                    f" {detail}\nRequest body:\n{request_dump}"
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

    # -- Cleanup ------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

"""OpenAI-compatible LLM chat completion client — pure HTTP transport (streaming).

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
    ChatChoice,
    ChatMessage,
    ChatResponse,
    CompletionUsage,
    LLMError,
    StreamingDelta,
    message_to_dict,
    tool_to_dict,
)
from mva.agent.tools import ToolDef


# ---------------------------------------------------------------------------
# Helper: ToolCallAccumulator
# ---------------------------------------------------------------------------


class ToolCallAccumulator:
    """Accumulates tool call deltas from streaming SSE chunks.

    OpenAI sends tool calls as a sequence of delta chunks.  Each chunk
    may contain a partial ``id``, partial ``name``, and/or a fragment
    of JSON ``arguments``.  This class merges them into complete tool
    call dicts.

    Usage::

        acc = ToolCallAccumulator()
        for chunk in stream:
            acc.feed(chunk.get("delta", {}).get("tool_calls", []))
            complete = acc.collect()  # list of fully accumulated calls
    """

    def __init__(self) -> None:
        self._calls: dict[int, dict[str, Any]] = {}

    def feed(self, deltas: list[dict[str, Any]]) -> None:
        """Feed raw tool call deltas from a single streaming chunk.

        Parameters
        ----------
        deltas:
            The ``tool_calls`` list from a choice delta object.  Each
            entry has at least an ``index`` key and optionally ``id``
            and ``function`` fields.
        """
        for tc in deltas:
            idx = tc.get("index", 0)
            if idx not in self._calls:
                self._calls[idx] = {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                }
            entry = self._calls[idx]
            if tc.get("id"):
                entry["id"] = tc["id"]
            fn = tc.get("function", {})
            if fn.get("name"):
                entry["function"]["name"] = fn["name"]
            if fn.get("arguments"):
                entry["function"]["arguments"] += fn["arguments"]

    def collect(self) -> list[dict[str, Any]]:
        """Return all accumulated tool calls, ordered by index.

        Returns an empty list when no tool calls have been fed.
        """
        result: list[dict[str, Any]] = []
        for idx in sorted(self._calls.keys()):
            entry = self._calls[idx]
            result.append({
                "id": entry["id"],
                "type": "function",
                "function": {
                    "name": entry["function"]["name"],
                    "arguments": entry["function"]["arguments"],
                },
            })
        return result

    def __bool__(self) -> bool:
        """``True`` if any tool calls have been accumulated."""
        return bool(self._calls)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LLMClient:
    """A thin HTTP streaming client for OpenAI-compatible chat completion APIs.

    This class is a **pure transport layer**: it builds HTTP requests,
    sends them, and parses streaming responses.  It does **not** load
    configuration files, manage provider state, or track available models.

    Only streaming is supported (``chat_stream``).  Non-streaming usage
    is not provided — callers that need a raw response should use
    ``chat_stream`` and collect the final delta.

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

    # -- Non-streaming chat (blocking wrapper around chat_stream) -----------

    def chat(
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
    ) -> ChatResponse:
        """Send a chat completion and return the complete response.

        This is a blocking convenience wrapper around :meth:`chat_stream`.
        It collects all streaming deltas and assembles a :class:`ChatResponse`.

        Parameters are identical to :meth:`chat_stream`.
        """
        last: StreamingDelta | None = None
        for last in self.chat_stream(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
            presence_penalty=presence_penalty,
            frequency_penalty=frequency_penalty,
            seed=seed,
            user=user,
            tools=tools,
            tool_choice=tool_choice,
            **extra_params,
        ):
            pass

        if last is None:
            return ChatResponse(choices=[
                ChatChoice(message=ChatMessage(role="assistant", content=""))
            ])

        return ChatResponse(
            id=last.id,
            model=last.model,
            choices=[
                ChatChoice(
                    message=ChatMessage(
                        role="assistant",
                        content=last.accumulated or "",
                        tool_calls=last.tool_calls,
                        reasoning_content=last.reasoning_content,
                    ),
                    finish_reason=last.finish_reason,
                )
            ],
            usage=last.usage,
        )

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
        """
        model = model or self.default_model
        if not model:
            raise ValueError(
                "A model must be specified via argument or default_model."
            )

        # Lazy import to avoid circular dependency with mva.utils
        from mva.utils import is_cancel_requested  # noqa: PLC0415

        body = self._build_request_body(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
            presence_penalty=presence_penalty,
            frequency_penalty=frequency_penalty,
            seed=seed,
            user=user,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
        )
        body.update(extra_params)

        tc_accum = ToolCallAccumulator()
        acc_content = ""
        acc_thinking = ""
        resp = None
        cancelled = False

        try:
            resp = self._session.post(
                f"{self.base_url}/chat/completions",
                json=body,
                stream=True,
                timeout=self.timeout,
            )
            self._raise_on_bad_status(resp, body)

            for chunk in self._iter_sse_chunks(resp):
                if is_cancel_requested():
                    cancelled = True
                    break

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta_obj = choice.get("delta", {})
                finish = choice.get("finish_reason")

                # --- Tool calls ---
                tc_accum.feed(delta_obj.get("tool_calls") or [])

                # --- Content ---
                delta = delta_obj.get("content", "")
                if delta:
                    acc_content += delta

                # --- Reasoning / thinking ---
                reasoning = (
                    delta_obj.get("reasoning_content")
                    or delta_obj.get("reasoning")
                    or ""
                )
                if reasoning:
                    acc_thinking += reasoning

                yield StreamingDelta(
                    id=chunk.get("id", ""),
                    model=chunk.get("model", ""),
                    delta=delta,
                    accumulated=acc_content,
                    thinking_delta=reasoning,
                    thinking=acc_thinking,
                    finish_reason=finish,
                    usage=self._parse_usage(chunk.get("usage")),
                    tool_calls=tc_accum.collect() or None,
                    reasoning_content=acc_thinking or None,
                )

        except requests.RequestException as exc:
            raise LLMError(f"Streaming request failed: {exc}") from exc
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass

        if cancelled:
            yield StreamingDelta(
                finish_reason="cancelled",
                accumulated=acc_content,
                thinking=acc_thinking,
                reasoning_content=acc_thinking or None,
                delta="",
                tool_calls=None,
            )

    # -- Cleanup ------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_request_body(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
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
        stream: bool = False,
    ) -> dict[str, Any]:
        """Build the JSON body for a chat completions request."""
        body: dict[str, Any] = {
            "model": model,
            "messages": [message_to_dict(m) for m in messages],
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty,
        }

        if stream:
            body["stream"] = True
        if max_tokens > 0:
            body["max_tokens"] = max_tokens
        if stop is not None:
            body["stop"] = stop
        if seed is not None:
            body["seed"] = seed
        if user is not None:
            body["user"] = user
        if tools:
            body["tools"] = [
                tool_to_dict(t.name, t.description, t.parameters) for t in tools
            ]
            body["tool_choice"] = tool_choice or "auto"

        return body

    @staticmethod
    def _iter_sse_chunks(
        resp: requests.Response,
    ) -> Generator[dict[str, Any]]:
        """Parse an SSE response body and yield JSON chunks.

        Each line should be ``data: <json>``.  Emits the parsed JSON
        dict for each valid data line.  Stops on ``data: [DONE]``.
        Skips empty lines and non-data lines silently.
        """
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8").strip()

            if not line.startswith("data: "):
                continue

            payload = line[6:].strip()
            if payload == "[DONE]":
                break

            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                continue

    @staticmethod
    def _raise_on_bad_status(resp: requests.Response, body: dict[str, Any]) -> None:
        """Raise :class:`LLMError` if the response status is not OK."""
        if resp.ok:
            return
        detail = resp.text[:500] if resp.text else "(no body)"
        request_dump = json.dumps(body, indent=2, default=str)[:2000]
        raise LLMError(
            f"Chat completion failed (HTTP {resp.status_code}): {detail}\n"
            f"Request body:\n{request_dump}"
        )

    @staticmethod
    def _parse_usage(raw: dict[str, Any] | None) -> CompletionUsage | None:
        """Parse a usage dict into a :class:`CompletionUsage`, or return None."""
        if not raw:
            return None
        return CompletionUsage(
            prompt_tokens=raw.get("prompt_tokens", 0),
            completion_tokens=raw.get("completion_tokens", 0),
            total_tokens=raw.get("total_tokens", 0),
        )

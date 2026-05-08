"""OpenAI-compatible LLM chat completion client with tool calling."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator

import requests

# ---------------------------------------------------------------------------
# Auto-load .env if python-dotenv is available
# ---------------------------------------------------------------------------


def _load_dotenv() -> None:
    """Load environment variables from a ``.env`` file in the CWD."""
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.cwd() / ".env")
    except ImportError:
        pass


_load_dotenv()


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


@dataclass
class ToolDef:
    """Definition of a tool (function) the model can call."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LLMClient:
    """A client for sending chat completion requests to an OpenAI-compatible API.

    Reads configuration from environment variables by default:
        LLM_BASE_URL   – base URL of the inference server (e.g. ``http://127.0.0.1:8002/v1``)
        LLM_API_KEY    – API key (use ``"no-key"`` for local servers)
        DEFAULT_MODEL  – default model name passed to the server

    All values can be overridden via constructor arguments.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout: int = 120,  # seconds
    ) -> None:
        self.base_url = (
            base_url
            if base_url is not None
            else os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8002/v1")
        ).rstrip("/")
        self.api_key = (
            api_key if api_key is not None else os.environ.get("LLM_API_KEY", "no-key")
        )
        self.default_model = (
            default_model
            if default_model is not None
            else os.environ.get("DEFAULT_MODEL", "")
        )
        self.timeout = timeout

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

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
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty,
        }

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

        raw: dict[str, Any] = dict()

        try:
            resp = self._session.post(url, json=body, timeout=self.timeout)
            resp.raise_for_status()
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

        url = f"{self.base_url}/chat/completions"

        body: dict[str, Any] = {
            "model": model,
            "messages": [_message_to_dict(m) for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty,
            "stream": True,
        }

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

        try:
            resp = self._session.post(url, json=body, stream=True, timeout=self.timeout)
            resp.raise_for_status()

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
                    name = entry["function"]["name"]
                    args_str = entry["function"]["arguments"]
                    try:
                        parsed_args = json.loads(args_str) if args_str else {}
                    except json.JSONDecodeError:
                        parsed_args = args_str  # keep raw if incomplete
                    tool_calls.append(
                        {
                            "id": entry["id"],
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": (
                                    parsed_args
                                    if isinstance(parsed_args, dict)
                                    else args_str
                                ),
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
                )

        except requests.RequestException as exc:
            raise LLMError(f"Streaming request failed: {exc}") from exc
        finally:
            if resp is not None:
                resp.close()

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


# ---------------------------------------------------------------------------
# Clean-up auto-load trace to not pollute public namespace
# ---------------------------------------------------------------------------

del _load_dotenv

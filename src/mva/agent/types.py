"""Data types and serialization helpers for the MVA agent.

These types are shared between the HTTP client, the session, and any UI
layer.  They are defined here rather than in ``client.py`` so that
consumers can import them without pulling in HTTP or configuration
dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Conversation message types
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
# Streaming types
# ---------------------------------------------------------------------------


@dataclass
class StreamingDelta:
    """A single streaming chunk from a streaming chat completion call."""

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
# Exceptions
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base exception for LLM / API client errors."""


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def message_to_dict(m: ChatMessage) -> dict[str, Any]:
    """Convert a ChatMessage to the dict format expected by the API."""
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_call_id is not None:
        d["tool_call_id"] = m.tool_call_id
    if m.tool_calls is not None:
        d["tool_calls"] = m.tool_calls
    if m.reasoning_content is not None:
        d["reasoning_content"] = m.reasoning_content
    return d


def tool_to_dict(name: str, description: str, parameters: dict) -> dict[str, Any]:
    """Convert a tool's name/description/parameters to the API dict format."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def parse_chat_response(raw: dict[str, Any]) -> ChatResponse:
    """Parse a raw JSON response dict into a :class:`ChatResponse`."""
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

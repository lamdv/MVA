"""MVA agent layer — LLM client + conversation session.

Re-exports everything from ``client.py`` and ``session.py`` so consumers
import from ``mva.agent``:

    from mva.agent import LLMClient, Session, StreamingDelta, ToolDef
"""

from mva.agent.client import (
    ChatChoice,
    ChatMessage,
    ChatResponse,
    CompletionUsage,
    LLMClient,
    LLMError,
    StreamingDelta,
    ToolDef,
)

from mva.agent.session import Session

__all__ = [
    "ChatChoice",
    "ChatMessage",
    "ChatResponse",
    "CompletionUsage",
    "LLMClient",
    "LLMError",
    "Session",
    "StreamingDelta",
    "ToolDef",
]

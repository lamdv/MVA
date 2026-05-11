"""MVA agent layer — LLM client, conversation session, tools, and skills.

The single public surface for the agent.  Everything needed to build a
conversational agent is accessible from ``mva.agent``::

    from mva.agent import (
        LLMClient, Session, ToolDef, execute_tool,
        SkillDef, discover_skills,
    )
"""

from mva.agent.types import (
    ChatChoice,
    ChatMessage,
    ChatResponse,
    CompletionUsage,
    LLMError,
    StreamingDelta,
    message_to_dict,
    parse_chat_response,
    tool_to_dict,
)
from mva.agent.client import LLMClient

# -- Re-export select tools symbols ----------------------------------------
# These must come before session import: session -> mva.utils -> mva.agent
from mva.agent.tools import execute_tool, get_tool_defs, ToolResult
from mva.agent.tools.base import ToolDef

# -- Re-export select skills symbols ---------------------------------------
# Same ordering constraint as above.
from mva.agent.skills import SkillDef, build_skills_prompt, discover_skills

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
    "ToolResult",
    # tools
    "execute_tool",
    "get_tool_defs",
    # skills
    "SkillDef",
    "build_skills_prompt",
    "discover_skills",
    # serialization
    "message_to_dict",
    "parse_chat_response",
    "tool_to_dict",
]

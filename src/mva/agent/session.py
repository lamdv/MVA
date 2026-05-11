"""Agent session — owns conversation history and the tool-calling loop.

A :class:`Session` is the reusable middle layer between a UI and the
:class:`~mva.agent.LLMClient`.  It owns the conversation history, runs the
tool-calling loop, and yields structured events for the UI to render.

Usage (CLI)::

    session = Session(client, tools, system_prompt, on_confirm=confirm_cb)
    for event in session.chat("hello"):
        render(event)

Usage (web)::

    session = Session(client, tools, system_prompt)
    for event in session.chat("hello"):
        socket.emit("event", event)
"""

from __future__ import annotations

import json
from typing import Any, Generator

from mva.agent import ChatMessage, LLMClient, LLMError, StreamingDelta, ToolDef
from mva.agent.tools import ToolResult, execute_tool
from mva.utils import build_messages, is_cancel_requested
from mva.utils import _mark_streaming_start, _mark_streaming_stop

MAX_TOOL_ROUNDS = 10

# ---------------------------------------------------------------------------
# Event types (simple dicts for maximum portability)
# ---------------------------------------------------------------------------

#: The model is emitting reasoning / thinking content.
#: ``{"type": "thinking", "content": str}``
THINKING = "thinking"

#: A regular text delta from the model.
#: ``{"type": "delta", "content": str}``
DELTA = "delta"

#: The model requested a tool call.
#: ``{"type": "tool_call", "id": str, "name": str, "args": dict}``
TOOL_CALL = "tool_call"

#: A tool was executed successfully or failed.
#: ``{"type": "tool_result", "id": str, "name": str, "content": str, "is_error": bool}``
TOOL_RESULT = "tool_result"

#: The turn is complete.  *content* is the final accumulated text.
#: ``{"type": "done", "content": str}``
DONE = "done"

#: The user cancelled the stream mid-response.
#: ``{"type": "cancelled"}``
CANCELLED = "cancelled"

#: An :class:`LLMError` occurred.
#: ``{"type": "error", "content": str}``
ERROR = "error"


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class Session:
    """Manages a single conversation with tool-calling support.

    Parameters
    ----------
    client : LLMClient
        The API client used for chat completions.
    tools : list[ToolDef]
        Tool definitions sent to the API.
    system_prompt : str
        The system prompt (built once by the caller, can be updated later).
    on_confirm : callable or None
        Called when a tool requires user confirmation.
        Signature: ``on_confirm(message: str, tool: str, args: dict) -> bool``
        Return ``True`` to approve, ``False`` to deny, or ``None`` to auto-deny.
    """

    def __init__(
        self,
        client: LLMClient,
        tools: list[ToolDef],
        system_prompt: str,
        *,
        on_confirm: Any = None,
    ) -> None:
        self.client = client
        self.tools = tools[:]
        self._system_prompt = system_prompt
        self.on_confirm = on_confirm

        # Owned state
        self.history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        """The current system prompt."""
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value

    def clear(self) -> None:
        """Clear the conversation history (e.g. on ``/clear``)."""
        self.history.clear()

    def rebuild_messages(self, new_user_msg: str = "") -> list[ChatMessage]:
        """Build a message list from current history + system prompt.

        UI code normally doesn't need to call this — :meth:`chat` handles
        it internally.  Useful for inspection or test assertions.
        """
        msgs = build_messages(self._system_prompt, self.history, new_user_msg)
        return [m for m in msgs if m.role != "user" or m.content]

    def chat(
        self,
        user_message: str,
        *,
        print_mode: bool = False,
    ) -> Generator[dict[str, Any]]:
        """Process a user message through the tool-calling loop.

        Appends the user message to *history*, then runs the tool-calling
        loop (text ↔ tool calls ↔ tool results), yielding events for the
        UI to render.

        Parameters
        ----------
        user_message : str
            The user's input text.
        print_mode : bool
            When ``True``, confirmation prompts are auto-denied
            (used for non-interactive ``--print`` mode).

        Yields
        ------
        dict
            Event dicts with at least a ``"type"`` key.
            See module-level constants for the full list.
        """
        # Record user input
        self.history.append({"role": "user", "content": user_message})

        messages = self.rebuild_messages("")
        # Drop the trailing empty user message from build_messages
        messages = [m for m in messages if m.role != "user" or m.content]

        yield from self._handle_turn(messages, print_mode=print_mode)

    def close(self) -> None:
        """Release client resources."""
        self.client.close()

    # ------------------------------------------------------------------
    # Internal: tool-calling loop
    # ------------------------------------------------------------------

    def _handle_turn(
        self,
        messages: list[ChatMessage],
        *,
        print_mode: bool = False,
    ) -> Generator[dict[str, Any]]:
        """Run the tool-calling loop for a single turn.

        Keeps sending tool results back to the model until it responds
        with text (``finish_reason == "stop"``) or hits the round limit.
        """
        rounds = 0

        while rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            final_tool_calls: list[dict[str, Any]] | None = None
            final_delta: StreamingDelta | None = None
            cancelled = False
            _emitted_tc_count: int = 0  # track tool calls already yielded

            # Mark streaming active so Ctrl+C cancels instead of exiting
            _mark_streaming_start()
            try:
                # Stream from the LLM
                for delta in self.client.chat_stream(
                    messages, tools=self.tools if self.tools else None
                ):
                    # Check for user cancellation
                    if is_cancel_requested():
                        cancelled = True
                        break

                # Yield thinking / delta events
                if delta.thinking_delta:
                    yield {"type": THINKING, "content": delta.thinking_delta}
                if delta.delta:
                    yield {"type": DELTA, "content": delta.delta}

                if delta.finish_reason == "cancelled":
                    cancelled = True
                    break

                # Yield tool-call events as soon as they appear in the stream,
                # before the stream finishes.  New tool calls are detected by
                # checking whether the accumulated list has grown.
                if delta.tool_calls:
                    final_tool_calls = delta.tool_calls
                    while len(delta.tool_calls) > _emitted_tc_count:
                        tc = delta.tool_calls[_emitted_tc_count]
                        _emitted_tc_count += 1
                        yield {
                            "type": TOOL_CALL,
                            "id": tc.get("id", ""),
                            "name": tc["function"]["name"],
                            "args": tc["function"]["arguments"],
                        }
                final_delta = delta
            finally:
                _mark_streaming_stop()

            if cancelled:
                yield {"type": CANCELLED}
                # Still record partial response in history
                if final_delta and (
                    final_delta.accumulated or final_delta.reasoning_content
                ):
                    self.history.append({
                        "role": "assistant",
                        "content": final_delta.accumulated,
                        "reasoning_content": final_delta.reasoning_content,
                    })
                return

            # --- Tool calls: execute and loop back ---
            if (
                final_tool_calls
                and final_delta
                and final_delta.finish_reason == "tool_calls"
            ):
                # Record assistant entry with tool calls
                self.history.append({
                    "role": "assistant",
                    "content": final_delta.accumulated or "",
                    "tool_calls": final_tool_calls,
                    "reasoning_content": final_delta.reasoning_content,
                })

                # Execute each tool call
                # (TOOL_CALL events were already emitted during streaming)
                for tc in final_tool_calls:
                    tc_id = tc.get("id", "")
                    fn_name = tc["function"]["name"]
                    fn_args = tc["function"]["arguments"]
                    if isinstance(fn_args, str):
                        try:
                            fn_args = json.loads(fn_args)
                        except json.JSONDecodeError:
                            fn_args = {}

                    result = self._execute_with_confirmation(
                        fn_name, fn_args, print_mode=print_mode
                    )

                    yield {
                        "type": TOOL_RESULT,
                        "id": tc_id,
                        "name": fn_name,
                        "content": result.content,
                        "is_error": result.is_error,
                    }

                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result.content,
                    })

                # Rebuild messages with updated history
                messages = self.rebuild_messages("")
                messages = [m for m in messages if m.role != "user" or m.content]
                continue

            # --- Normal stop: record final assistant message ---
            if final_delta and (final_delta.accumulated or final_delta.reasoning_content):
                self.history.append({
                    "role": "assistant",
                    "content": final_delta.accumulated,
                    "reasoning_content": final_delta.reasoning_content,
                })

            yield {
                "type": DONE,
                "content": (final_delta.accumulated if final_delta else ""),
            }
            return

        # --- Max rounds reached ---
        msg = "⚠ Max tool-calling rounds reached. Stopping."
        self.history.append({
            "role": "assistant",
            "content": "I've reached the tool-calling limit. Please ask a simpler question.",
        })
        yield {"type": DONE, "content": msg}

    # ------------------------------------------------------------------
    # Internal: tool execution with confirmation
    # ------------------------------------------------------------------

    def _execute_with_confirmation(
        self,
        fn_name: str,
        fn_args: dict[str, Any],
        *,
        print_mode: bool = False,
    ) -> ToolResult:
        """Execute a tool, handling confirmation loops via the callback."""
        result = execute_tool(fn_name, fn_args)

        while result.needs_confirmation:
            if print_mode:
                msg = result.confirmation_message.split("\n")[0]
                return ToolResult(
                    content=f"Blocked (print mode): {msg}",
                    is_error=True,
                )

            if self.on_confirm is not None:
                approved = self.on_confirm(
                    result.confirmation_message,
                    result.confirmation_tool,
                    result.confirmation_args,
                )
            else:
                approved = False

            if approved:
                result = execute_tool(
                    result.confirmation_tool,
                    result.confirmation_args,
                    confirmed=True,
                )
            else:
                msg = result.confirmation_message.split("\n")[0]
                result = ToolResult(
                    content=f"Blocked by user: {msg}",
                    is_error=True,
                )

        return result

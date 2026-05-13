"""Agent session — owns conversation history and the tool-calling loop.

A :class:`Session` is the reusable middle layer between a UI and the
:class:`~mva.agent.LLMClient`.  It owns the conversation history, runs the
tool-calling loop, and yields structured events for the UI to render.
It also manages provider / model state on behalf of the UI.

Usage (CLI)::

    session = Session(tools, system_prompt, on_confirm=confirm_cb)
    for event in session.chat("hello"):
        render(event)

Usage (web)::

    session = Session(tools, system_prompt)
    for event in session.chat("hello"):
        socket.emit("event", event)
"""

from __future__ import annotations

import json
from typing import Any, Generator

from mva_core.agent.client import LLMClient
from mva_core.agent.types import ChatMessage, CompletionUsage, LLMError, StreamingDelta
from mva_core.tools import ToolDef, ToolResult, execute_tool
from mva_core._system import build_messages, is_cancel_requested
from mva_core._system import _mark_streaming_start, _mark_streaming_stop

DEFAULT_MAX_TOOL_ROUNDS = 10

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

    The session owns the :class:`LLMClient` instance and manages
    provider / model state.  Use :meth:`switch_provider` and
    :meth:`set_model` to change the active backend at runtime.

    Parameters
    ----------
    tools : list[ToolDef]
        Tool definitions sent to the API.
    system_prompt : str
        The system prompt (built once by the caller, can be updated later).
    client : LLMClient or None
        An optional pre-configured client.  When ``None``, a client is
        auto-created from ``model.yaml`` via :meth:`LLMClient.from_config`.
    on_confirm : callable or None
        Called when a tool requires user confirmation.
        Signature: ``on_confirm(message: str, tool: str, args: dict) -> bool``
        Return ``True`` to approve, ``False`` to deny, or ``None`` to auto-deny.
    max_tool_rounds : int
        Maximum number of tool-calling rounds per turn.
        Defaults to :const:`DEFAULT_MAX_TOOL_ROUNDS` (10).
    """

    def __init__(
        self,
        tools: list[ToolDef],
        system_prompt: str,
        *,
        client: LLMClient | None = None,
        on_confirm: Any = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ) -> None:
        self.client = client or LLMClient.from_config()
        self.tools = tools[:]
        self._system_prompt = system_prompt
        self.on_confirm = on_confirm
        self.max_tool_rounds = max_tool_rounds

        # Provider / model state (used by CLI for /model, /provider commands)
        self.current_provider: str | None = None
        self._available_models: list[str] = []

        # Load provider name and available models from config if possible
        self._refresh_provider_state()

        # Owned state
        self.history: list[dict[str, Any]] = []

        # Token usage tracking
        self.total_usage = CompletionUsage()
        """Cumulative token usage across all turns in this session."""

    # ------------------------------------------------------------------
    # Provider / model management
    # ------------------------------------------------------------------

    def _refresh_provider_state(self) -> None:
        """Read the active provider name and model list from config."""
        try:
            from mva_core.config import load_config  # noqa: PLC0415
            cfg = load_config()
            self.current_provider = cfg.provider
            provider_cfg = cfg.providers.get(cfg.provider)
            if provider_cfg:
                self._available_models = list(provider_cfg.models)
        except Exception:
            pass

    def switch_provider(self, provider_name: str) -> bool:
        """Switch to a different provider from the config file.

        Re-loads ``model.yaml``, applies the named provider's
        configuration to the internal client, and updates
        *current_provider* and *available_models*.

        Returns ``True`` on success, ``False`` if the provider is not found.
        """
        from mva_core.config import reload_config  # noqa: PLC0415

        try:
            cfg = reload_config()
        except Exception:
            return False

        if provider_name not in cfg.providers:
            return False

        provider = cfg.providers[provider_name]
        # Reconfigure the existing client in-place
        self.client.base_url = provider.base_url.rstrip("/")
        self.client.api_key = provider.api_key
        self.client._session.headers.update(
            {"Authorization": f"Bearer {self.client.api_key}"}
        )
        self.client.default_model = provider.default_model
        self.client.timeout = provider.timeout

        self.current_provider = provider_name
        self._available_models = list(provider.models)
        return True

    def set_model(self, model_name: str) -> bool:
        """Set the active model within the current provider.

        If *available_models* is non-empty, *model_name* must appear in
        that list (case-insensitive comparison).  When the list is
        empty, the model is set unconditionally (backward-compatible
        behaviour).

        Returns ``True`` on success.
        """
        if self._available_models:
            lower = model_name.lower()
            if lower not in {m.lower() for m in self._available_models}:
                return False
            # Preserve the canonical casing from the config
            for m in self._available_models:
                if m.lower() == lower:
                    model_name = m
                    break
        self.client.default_model = model_name
        return True

    @property
    def available_models(self) -> list[str]:
        """Return the list of available model names for the current
        provider (may be empty if none were declared in config)."""
        return list(self._available_models)

    def test_connection(self) -> tuple[bool, str]:
        """Test the current provider connection with a minimal request.

        Delegates to :meth:`LLMClient.test_connection`.

        Returns
        -------
        (True, "")
            The provider responded successfully.
        (False, error_message)
            Something went wrong — see the string for details.
        """
        return self.client.test_connection()

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
        auto_confirm: bool = False,
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
        auto_confirm : bool
            When ``True``, security confirmations are auto-approved
            (used for non-interactive ``--yes`` mode).

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

        yield from self._handle_turn(
            messages, print_mode=print_mode, auto_confirm=auto_confirm
        )

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
        auto_confirm: bool = False,
    ) -> Generator[dict[str, Any]]:
        """Run the tool-calling loop for a single turn.

        Keeps sending tool results back to the model until it responds
        with text (``finish_reason == "stop"``) or hits the round limit.
        """
        rounds = 0

        while rounds < self.max_tool_rounds:
            rounds += 1
            final_tool_calls: list[dict[str, Any]] | None = None
            final_delta: StreamingDelta | None = None
            cancelled = False
            _tool_calls_seen: bool = False  # avoid re-emitting the heads-up

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

                    # Yield thinking / delta events as they arrive
                    if delta.thinking_delta:
                        yield {"type": THINKING, "content": delta.thinking_delta}
                    if delta.delta:
                        yield {"type": DELTA, "content": delta.delta}

                    if delta.finish_reason == "cancelled":
                        cancelled = True
                        break

                    # Stream tool calls as they form — yield the
                    # current (possibly partial) name + args immediately
                    # so the user sees what's happening without waiting
                    # for the stream to finish.  The renderer truncates
                    # args to 100 chars per value.
                    if delta.tool_calls:
                        final_tool_calls = delta.tool_calls
                        if not _tool_calls_seen:
                            _tool_calls_seen = True
                            for tc in final_tool_calls:
                                name = tc["function"]["name"] or "…"
                                yield {
                                    "type": TOOL_CALL,
                                    "id": tc.get("id", ""),
                                    "name": name,
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
                # Emit TOOL_CALL events now with fully formed arguments
                # (marked ``final`` so the renderer skips the tool name
                # and only re-prints the now-complete args).
                for tc in final_tool_calls:
                    yield {
                        "type": TOOL_CALL,
                        "id": tc.get("id", ""),
                        "name": tc["function"]["name"],
                        "args": tc["function"]["arguments"],
                        "final": True,
                    }

                # Record assistant entry with tool calls
                self.history.append({
                    "role": "assistant",
                    "content": final_delta.accumulated or "",
                    "tool_calls": final_tool_calls,
                    "reasoning_content": final_delta.reasoning_content,
                })

                # Execute each tool call
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
                        fn_name, fn_args,
                        print_mode=print_mode, auto_confirm=auto_confirm,
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

            # Track token usage
            event_usage = None
            if final_delta and final_delta.usage:
                event_usage = {
                    "prompt_tokens": final_delta.usage.prompt_tokens,
                    "completion_tokens": final_delta.usage.completion_tokens,
                    "total_tokens": final_delta.usage.total_tokens,
                }
                self.total_usage.prompt_tokens += final_delta.usage.prompt_tokens
                self.total_usage.completion_tokens += final_delta.usage.completion_tokens
                self.total_usage.total_tokens += final_delta.usage.total_tokens

            yield {
                "type": DONE,
                "content": (final_delta.accumulated if final_delta else ""),
                "usage": event_usage,
            }
            return

        # --- Max rounds reached ---
        msg = "⚠ Max tool-calling rounds reached. Stopping."
        self.history.append({
            "role": "assistant",
            "content": "I've reached the tool-calling limit. Please ask a simpler question.",
        })
        yield {"type": DONE, "content": msg, "usage": None}

    # ------------------------------------------------------------------
    # Internal: tool execution with confirmation
    # ------------------------------------------------------------------

    def _execute_with_confirmation(
        self,
        fn_name: str,
        fn_args: dict[str, Any],
        *,
        print_mode: bool = False,
        auto_confirm: bool = False,
    ) -> ToolResult:
        """Execute a tool, handling confirmation loops via the callback."""
        result = execute_tool(fn_name, fn_args)

        while result.needs_confirmation:
            if auto_confirm:
                # Trust the model — auto-approve
                result = execute_tool(
                    result.confirmation_tool,
                    result.confirmation_args,
                    confirmed=True,
                )
                continue

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

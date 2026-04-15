from __future__ import annotations

import json
import time
import uuid
import warnings
from pathlib import Path
from typing import Any, Generator

from ..utils.llm_client import LlamaClient, LLMError, get_client
from ..utils.log import get_logger
from .tools import (          # ← Updated imports
    Tool,
    init_sandbox,
    get_available_tools,
    execute_tool,
    SandboxError,
    ToolsNotSupportedError,
    load_tools_from_directory,
)
from .skills import SkillCatalog
from .telemetry import TelemetryStore

_log = get_logger("agent")

# Deferred import to avoid circular dependency
def _get_reflection_engine():
    """Lazy import to avoid circular dependency with Agent."""
    from .reflection import ReflectionEngine
    return ReflectionEngine


class Agent:
    """LLM agent with tool-calling capability using the centralized sandboxed tools.py"""

    def __init__(
        self,
        client: LlamaClient | None = None,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        workspace_dir: Path | str | None = None,        # ← New: sandbox workspace
        tools_dir: Path | str | None = None,
        skills_dir: Path | str | None = None,
        max_iterations: int = 50,
        telemetry_dir: Path | str | None = None,        # ← New: telemetry for self-improvement
        reflection_config: dict | None = None,          # ← New: reflection triggers
    ) -> None:
        self.client = client or get_client()
        self.system_prompt = system_prompt
        self.model = model or self.client.default_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations

        # Sandbox & Tools (now centralized)
        self.workspace_dir = Path(workspace_dir).resolve() if workspace_dir else None
        self.tools_dir: Path | None = Path(tools_dir).resolve() if tools_dir else None

        # Skill catalog
        self._skills = SkillCatalog(skills_dir)

        # Telemetry for self-improvement (Phase 1: Observe)
        self._telemetry: TelemetryStore | None = None
        self._session_id: str | None = None
        if telemetry_dir:
            self._telemetry = TelemetryStore(Path(telemetry_dir))
            self._session_id = self._telemetry.new_session(self.model)
            _log.debug(f"Telemetry enabled, session_id={self._session_id}")

        # Reflection for self-improvement (Phase 2: Reflect)
        self._reflection_engine = None
        self._reflection_config = reflection_config or {}
        if self._telemetry and self._reflection_config:
            ReflectionEngine = _get_reflection_engine()
            self._reflection_engine = ReflectionEngine(
                agent=self,
                telemetry_store=self._telemetry,
                config=self._reflection_config,
            )
            _log.debug(f"Reflection enabled with config: {self._reflection_config}")

        # Initialize sandbox (single folder enforcement)
        if self.workspace_dir:
            init_sandbox(self.workspace_dir)
        else:
            init_sandbox()  # uses default /tmp/agent_workspace

        # Load tools from directory (if provided)
        if self.tools_dir:
            load_tools_from_directory(self.tools_dir)

        # Auto-register load_skill tool
        if skills_dir:
            self._skills.refresh()
            self._register_load_skill_tool()
            self.system_prompt = self._skills.system_prompt_injection(self.system_prompt)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(self, history: list[dict]) -> list[dict]:
        messages = list(history)
        if self.system_prompt:
            return [{"role": "system", "content": self.system_prompt}, *messages]
        return messages

    def _sampling_params(self) -> dict:
        params: dict = {"model": self.model, "temperature": self.temperature}
        if self.max_tokens is not None:
            params["max_tokens"] = self.max_tokens
        return params

    # ------------------------------------------------------------------
    # Tool management (Simplified - uses central tools.py)
    # ------------------------------------------------------------------

    def _tool_schemas(self) -> list[dict]:
        """Return OpenAI-compatible tool schemas from central registry."""
        schemas = get_available_tools()
        if schemas:
            _log.debug("Available tools: %s", [s["function"]["name"] for s in schemas])
        return schemas

    # def _execute_tool(self, name: str, args: dict) -> Any:
    #     """Execute tool through the centralized sandboxed tool service."""
    #     try:
    #         result = execute_tool(name, args)
    #         if result.get("success"):
    #             return result["result"]
    #         else:
    #             error_msg = result.get("error", "Unknown tool error")
    #             _log.warning("Tool execution failed: %s", error_msg)
    #             return f"Error: {error_msg}"
    #     except ToolsNotSupportedError as e:
    #         _log.warning(str(e))
    #         return f"Error: {e}"
    #     except SandboxError as e:
    #         _log.warning("Sandbox violation: %s", e)
    #         return f"SandboxError: {e}"
    #     except Exception as e:
    #         _log.error("Unexpected error in tool %s: %s", name, e)
    #         return f"Error: {e}"
    def _execute_tool(self, name: str, args: dict, iteration: int = 0) -> Any:
        """Execute tool through the centralized sandbox service.

        Arguments are normalized by execute_tool(), so we pass them as-is.

        Args:
            name: Tool name
            args: Tool arguments dict
            iteration: Current iteration number (for telemetry)

        Returns:
            Tool result or error message
        """
        # Telemetry: record start time and args
        t0 = time.monotonic()
        record = {
            "record_id": str(uuid.uuid4()),
            "session_id": self._session_id,
            "tool_name": name,
            "args_repr": json.dumps(args, default=str)[:512],
            "iteration": iteration,
            "success": False,
        }

        try:
            result = execute_tool(name, args)

            if result.get("success"):
                record["success"] = True
                _log.debug("Tool '%s' succeeded", name)
                return result["result"]
            else:
                error_msg = result.get("error", "Unknown error")
                record["success"] = False
                record["error"] = error_msg[:256]
                _log.warning("Tool '%s' failed: %s", name, error_msg)
                return f"Error: {error_msg}"

        except ToolsNotSupportedError as e:
            record["success"] = False
            record["error"] = str(e)[:256]
            _log.warning(str(e))
            return f"Error: {e}"
        except SandboxError as e:
            record["success"] = False
            record["error"] = f"SandboxError: {str(e)}"[:256]
            _log.warning("Sandbox violation in %s: %s", name, e)
            return f"SandboxError: {e}"
        except Exception as e:
            record["success"] = False
            record["error"] = str(e)[:256]
            _log.error("Unexpected error calling tool %s: %s", name, e)
            return f"Error: {e}"
        finally:
            # Telemetry: record latency and store
            record["latency_ms"] = (time.monotonic() - t0) * 1000
            if self._telemetry and self._session_id:
                self._telemetry.record_tool_call(record)
    def _finalize_session(self, history: list[dict]) -> None:
        """Finalize a session and prepare for reflection/improvement.

        This is called at the end of stream() and run().
        Exceptions are caught and logged — never propagate.

        Args:
            history: Full message history for the session
        """
        if not self._telemetry or not self._session_id:
            return

        try:
            # Close the session (calculate final stats)
            session_data = self._telemetry.close_session(self._session_id)

            # Update cross-session memory
            self._telemetry.update_memory(session_data)

            _log.info(
                f"Session finalized: {self._session_id}, "
                f"total_calls={session_data.get('stats', {}).get('total_tool_calls', 0)}, "
                f"success_rate={session_data.get('stats', {}).get('success_rate', 1.0):.1%}"
            )

            # Phase 2: Reflect (if enabled)
            if self._reflection_engine:
                try:
                    reflection_md = self._reflection_engine.maybe_reflect(
                        self._session_id, history
                    )
                    if reflection_md:
                        _log.info(f"Reflection generated for session {self._session_id}")
                except Exception as e:
                    _log.error(f"Error during reflection: {e}")

        except Exception as e:
            _log.error(f"Error finalizing session: {e}")

    # ------------------------------------------------------------------
    # Skill support
    # ------------------------------------------------------------------

    def _register_load_skill_tool(self) -> None:
        """Register the built-in load_skill tool."""

        def load_skill(name: str) -> str:
            """Load full instructions for a skill by name.
            Use this when you decide to apply a specific skill."""
            return self._skills.load_skill(name)

        # Register via central tools system (optional - if you want it as a tool)
        from .tools import register_tool
        register_tool(load_skill)

    # ------------------------------------------------------------------
    # Main communication methods
    # ------------------------------------------------------------------

    def stream(self, history: list[dict]) -> Generator[dict, None, None]:
        """Stream responses with transparent tool-call execution."""
        messages = self._build_messages(history)
        _log.debug("stream: starting with %d message(s), max_iterations=%d", len(history), self.max_iterations)

        for iteration in range(self.max_iterations):
            accumulated: dict[int, dict] = {}
            content_parts: list[str] = []
            had_tool_calls = False

            try:
                for chunk in self.client.complete_stream(
                    messages,
                    tools=self._tool_schemas() if self._tool_schemas() else None,
                    tool_choice="auto" if self._tool_schemas() else "",
                    **self._sampling_params(),
                ):
                    if chunk["type"] == "tool_call_delta":
                        had_tool_calls = True
                        idx = chunk.get("index", 0)
                        if idx not in accumulated:
                            accumulated[idx] = {"id": "", "name": "", "arguments": ""}
                        tc = accumulated[idx]
                        if chunk.get("id"):
                            tc["id"] = chunk["id"]
                        fn = chunk.get("function", {})
                        if fn.get("name"):
                            tc["name"] += fn["name"]
                        if fn.get("arguments"):
                            tc["arguments"] += fn["arguments"]
                    else:
                        if chunk["type"] == "content":
                            content_parts.append(chunk["content"])
                        yield chunk
                        if chunk["type"] == "error":
                            return
            except LLMError as exc:
                if exc.status_code in (400, 422) and self._tool_schemas():
                    yield {"type": "error", "content": 
                        "Server rejected tool-call request. Server may not support function calling."}
                    return
                raise

            if not had_tool_calls:
                _log.debug("stream: iteration %d completed with no tool calls", iteration)
                return

            # Append assistant message
            tool_calls_list = [
                {
                    "id": accumulated[i]["id"],
                    "type": "function",
                    "function": {
                        "name": accumulated[i]["name"],
                        "arguments": accumulated[i]["arguments"],
                    },
                }
                for i in sorted(accumulated)
            ]

            _log.debug("stream: iteration %d has %d tool call(s): %s",
                      iteration, len(tool_calls_list),
                      [tc["function"]["name"] for tc in tool_calls_list])

            messages.append({
                "role": "assistant",
                "content": "".join(content_parts) or None,
                "tool_calls": tool_calls_list,
            })

            # Execute tools
            tool_messages = []
            for i in sorted(accumulated):
                tc = accumulated[i]
                name = tc["name"]
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except Exception as e:
                    _log.warning("stream: failed to parse JSON arguments for tool '%s': %s", name, e)
                    args = {}

                yield {"type": "tool_start", "name": name, "args": args}

                try:
                    result = self._execute_tool(name, args, iteration=iteration)
                except Exception as exc:
                    _log.warning("stream: tool execution failed for '%s': %s", name, exc)
                    result = f"Error: {exc}"

                yield {"type": "tool_use", "name": name, "result": str(result)}
                tool_messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": str(result)}
                )

            messages.extend(tool_messages)

        yield {"type": "content", "content": "[max_iterations reached]"}
        self._finalize_session(messages)

    def complete(self, history: list[dict]) -> str:
        """Non-streaming response without tool loop."""
        messages = self._build_messages(history)
        return self.client.complete(messages, **self._sampling_params())

    def run(self, history: list[dict]) -> str:
        """Non-streaming tool-calling loop. Returns final assistant reply."""
        messages = self._build_messages(history)
        _log.debug("run: starting with %d message(s), max_iterations=%d", len(history), self.max_iterations)

        for iteration in range(self.max_iterations):
            _log.debug("run: iteration %d", iteration)
            try:
                msg = self.client.chat(
                    messages,
                    tools=self._tool_schemas() if self._tool_schemas() else None,
                    tool_choice="auto" if self._tool_schemas() else "",
                    **self._sampling_params(),
                )
            except LLMError as exc:
                if exc.status_code in (400, 422) and self._tool_schemas():
                    raise RuntimeError(
                        "Server rejected tool-call request. Server may not support function calling."
                    ) from exc
                raise

            messages.append(msg)

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                _log.debug("run: iteration %d completed with no tool calls", iteration)
                self._finalize_session(messages)
                return msg.get("content", "")

            _log.debug("run: iteration %d has %d tool call(s): %s",
                      iteration, len(tool_calls),
                      [tc["function"]["name"] for tc in tool_calls])

            # Execute tools
            tool_messages = []
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                except Exception as e:
                    _log.warning("run: failed to parse JSON arguments for tool '%s': %s", name, e)
                    args = {}

                try:
                    result = self._execute_tool(name, args, iteration=iteration)
                except Exception as exc:
                    _log.warning("run: tool execution failed for '%s': %s", name, exc)
                    result = f"Error: {exc}"

                tool_messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": str(result)}
                )

            messages.extend(tool_messages)

        self._finalize_session(messages)
        return "[max_iterations reached]"

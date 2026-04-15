"""Reflection system for agent self-improvement (Phase 2: Reflect).

Analyzes session telemetry to identify:
- Tool performance patterns
- Missing capabilities
- Skill opportunities
- Performance bottlenecks

Outputs markdown reflections with structured insights for Phase 3 (Improve).
"""

import json
import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


class ReflectionEngine:
    """Analyzes session telemetry and generates reflection insights.
    
    Uses LLM (non-tool-loop) to analyze what happened in a session
    and identify opportunities for improvement.
    """

    def __init__(
        self,
        agent: Any,  # Agent instance (imported locally to avoid circular imports)
        telemetry_store: Any,  # TelemetryStore instance
        config: dict | None = None,
    ):
        """Initialize reflection engine.
        
        Args:
            agent: Agent instance with complete() method
            telemetry_store: TelemetryStore for loading session data
            config: Reflection config with triggers (reflect_always, fail_rate_threshold, etc)
        """
        self.agent = agent
        self.telemetry_store = telemetry_store
        self.config = config or {}

    def maybe_reflect(
        self, session_id: str, history: list[dict]
    ) -> str | None:
        """Decide whether to reflect based on triggers.
        
        Args:
            session_id: Session UUID
            history: Full message history
        
        Returns:
            Reflection markdown if triggered, None otherwise
        """
        if not session_id:
            return None

        # Load session data
        session_file = self.telemetry_store.sessions_dir / f"{session_id}.json"
        if not session_file.exists():
            _log.warning(f"Session file not found: {session_file}")
            return None

        try:
            with open(session_file) as f:
                session_data = json.load(f)
        except Exception as e:
            _log.error(f"Failed to load session data: {e}")
            return None

        # Check triggers
        trigger = self._check_triggers(session_data)
        if not trigger:
            _log.debug(f"No reflection trigger for session {session_id}")
            return None

        _log.info(f"Reflection triggered for session {session_id}: {trigger}")

        # Generate reflection
        return self.reflect(session_id, session_data, history, trigger)

    def _check_triggers(self, session_data: dict) -> str | None:
        """Check if any reflection trigger condition is met.
        
        Args:
            session_data: Session JSON data
        
        Returns:
            Trigger name if condition met, None otherwise
        """
        stats = session_data.get("stats", {})
        tool_calls = session_data.get("tool_calls", [])

        # Trigger 1: reflect_always (if tools were called)
        if self.config.get("reflect_always") and len(tool_calls) > 0:
            return "reflect_always"

        # Trigger 2: fail_rate_threshold
        fail_threshold = self.config.get("fail_rate_threshold")
        if fail_threshold is not None and len(tool_calls) > 0:
            success_rate = stats.get("success_rate", 1.0)
            if success_rate < (1.0 - fail_threshold):
                return f"high_failure_rate (success_rate={success_rate:.1%})"

        # Trigger 3: slow_tool_threshold_ms
        slow_threshold = self.config.get("slow_tool_threshold_ms")
        if slow_threshold is not None:
            for call in tool_calls:
                if call.get("latency_ms", 0) > slow_threshold:
                    return f"slow_tool ({call.get('tool_name')} took {call.get('latency_ms'):.0f}ms)"

        return None

    def reflect(
        self,
        session_id: str,
        session_data: dict,
        history: list[dict],
        trigger: str,
    ) -> str:
        """Generate reflection using LLM analysis.
        
        Args:
            session_id: Session UUID
            session_data: Session telemetry data
            history: Message history
            trigger: What triggered reflection
        
        Returns:
            Markdown reflection content
        """
        # Build reflection prompt
        prompt = self._build_prompt(session_id, session_data, trigger)

        _log.debug(f"Calling agent.complete() for reflection (trigger: {trigger})")

        try:
            # Use complete() — no tool loop, single LLM call
            reflection_md = self.agent.complete([
                {"role": "user", "content": prompt}
            ])

            # Store the reflection
            self.telemetry_store.store_reflection(session_id, reflection_md)
            _log.info(f"Reflection stored for session {session_id}")

            return reflection_md

        except Exception as e:
            _log.error(f"Failed to generate reflection: {e}")
            return ""

    def _build_prompt(
        self, session_id: str, session_data: dict, trigger: str
    ) -> str:
        """Build LLM prompt for reflection.
        
        Args:
            session_id: Session UUID
            session_data: Session telemetry
            trigger: Reflection trigger
        
        Returns:
            Markdown prompt for LLM
        """
        tool_calls = session_data.get("tool_calls", [])
        stats = session_data.get("stats", {})
        tools_used = stats.get("tools_used", [])
        success_rate = stats.get("success_rate", 1.0)
        failed_calls = [c for c in tool_calls if not c.get("success", True)]

        # Build tool statistics summary
        tool_stats = {}
        for call in tool_calls:
            tool_name = call.get("tool_name")
            if tool_name not in tool_stats:
                tool_stats[tool_name] = {"calls": 0, "failures": 0, "latencies": []}
            tool_stats[tool_name]["calls"] += 1
            if not call.get("success", True):
                tool_stats[tool_name]["failures"] += 1
            tool_stats[tool_name]["latencies"].append(call.get("latency_ms", 0))

        # Get recent past reflections
        past_reflections = self.telemetry_store.get_recent_reflections(n=3)

        # Build markdown prompt
        prompt = f"""# Session Reflection: {session_id}

You are analyzing a tool-calling session. Your job is to identify what worked, what failed, and what opportunities exist for improvement.

## Session Summary

- **Tools Called:** {len(tool_calls)}
- **Success Rate:** {success_rate:.1%}
- **Failed Calls:** {len(failed_calls)}
- **Tools Used:** {", ".join(tools_used) or "None"}
- **Trigger:** {trigger}

## Tool Performance

"""

        for tool_name, stats_data in sorted(tool_stats.items()):
            avg_latency = (
                sum(stats_data["latencies"]) / len(stats_data["latencies"])
                if stats_data["latencies"]
                else 0
            )
            prompt += f"- **{tool_name}**: {stats_data['calls']} calls, "
            prompt += f"{stats_data['failures']} failures, "
            prompt += f"avg {avg_latency:.1f}ms\n"

        if failed_calls:
            prompt += "\n## Failed Tool Calls\n\n"
            for call in failed_calls[:5]:  # Show first 5 failures
                error = call.get("error", "Unknown error")[:100]
                prompt += f"- **{call.get('tool_name')}**: {error}\n"

        if past_reflections:
            prompt += "\n## Past Lessons (from recent sessions)\n\n"
            for i, reflection in enumerate(past_reflections, 1):
                # Extract summary from past reflection
                lines = reflection.split("\n")
                summary = " ".join(lines[5:10]).strip()[:200]
                prompt += f"**Session {i}:** {summary}...\n"

        # Instruction for LLM
        prompt += """
## Your Task

Analyze this session and provide structured insights:

### What Happened
Write 2-4 sentences explaining what the agent tried to do and how well it went.

### Tool Insights
Create a markdown table with columns:
| Tool | Issue | Detail |
|------|-------|--------|
| tool_name | missing|slow|redundant | Why this is a problem |

Examples of issues:
- **missing**: Tool doesn't exist but would be useful (e.g., "No HTTP library")
- **slow**: Tool works but takes too long
- **redundant**: Duplicate of another tool

### Skill Insights
Create a markdown table with columns:
| Pattern | Action | Name |
|---------|--------|------|
| What pattern did you see? | create|update|none | Suggested skill name |

Examples:
- Pattern: "Fetch data from HTTP APIs" → Action: create → Name: http-fetch
- Pattern: "CSV file analysis" → Action: create → Name: csv-analysis

### Recommendations
List 2-3 specific improvements that would help in future sessions.

**IMPORTANT FORMATTING:**
- Use markdown tables only (not JSON)
- Keep issue/pattern descriptions brief (one line)
- Suggest action only for real opportunities
- Do NOT suggest external packages (use stdlib only)

---
Write your reflection now:
"""

        return prompt

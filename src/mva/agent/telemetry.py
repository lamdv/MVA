"""Telemetry system for agent self-improvement (Observe phase).

Records tool calls, latencies, and success/failure metrics to JSON files.
Thread-safe append operations for concurrent recording.
"""

import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TelemetryStore:
    """Manages JSON-based telemetry for self-improvement.

    Data flow:
    - new_session() → creates session_id, initializes empty session.json
    - record_tool_call() → appends record to session.json (thread-safe)
    - close_session() → finalizes session with statistics
    - store_reflection() → saves markdown reflection
    - update_memory() → updates cross-session aggregates
    """

    def __init__(self, telemetry_dir: Path):
        """Initialize telemetry store.

        Args:
            telemetry_dir: Root directory for all telemetry data
        """
        self.telemetry_dir = Path(telemetry_dir)
        self.sessions_dir = self.telemetry_dir / "sessions"
        self.reflections_dir = self.telemetry_dir / "reflections"
        self.generated_tools_dir = self.telemetry_dir / "generated_tools"
        self.generated_skills_dir = self.telemetry_dir / "generated_skills"
        self.memory_file = self.telemetry_dir / "memory.json"

        # Create directories
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.reflections_dir.mkdir(parents=True, exist_ok=True)
        self.generated_tools_dir.mkdir(parents=True, exist_ok=True)
        self.generated_skills_dir.mkdir(parents=True, exist_ok=True)

        # Thread safety for concurrent writes
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

        logger.debug(f"TelemetryStore initialized at {self.telemetry_dir}")

    def _get_session_lock(self, session_id: str) -> threading.Lock:
        """Get or create a lock for a session."""
        with self._lock:
            if session_id not in self._locks:
                self._locks[session_id] = threading.Lock()
            return self._locks[session_id]

    def new_session(self, model: str) -> str:
        """Start a new session.

        Args:
            model: LLM model name

        Returns:
            Session ID (UUID)
        """
        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "model": model,
            "tool_calls": [],
            "stats": {
                "total_tool_calls": 0,
                "failed_tool_calls": 0,
                "success_rate": 1.0,
                "tools_used": [],
            },
        }

        session_file = self.sessions_dir / f"{session_id}.json"
        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2)

        logger.debug(f"New session {session_id} with model {model}")
        return session_id

    def record_tool_call(self, record: dict) -> None:
        """Record a tool call (thread-safe append).

        Args:
            record: Tool call record dict with keys:
                - record_id: UUID
                - session_id: Session UUID
                - tool_name: str
                - args_repr: JSON string (first 512 chars)
                - success: bool
                - error: str (if failed)
                - latency_ms: float
                - iteration: int
        """
        session_id = record.get("session_id")
        if not session_id:
            logger.warning("record_tool_call: missing session_id")
            return

        session_file = self.sessions_dir / f"{session_id}.json"
        lock = self._get_session_lock(session_id)

        with lock:
            try:
                # Read current session
                with open(session_file, "r") as f:
                    session_data = json.load(f)

                # Append record
                session_data["tool_calls"].append(record)

                # Write back
                with open(session_file, "w") as f:
                    json.dump(session_data, f, indent=2)

                logger.debug(
                    f"Recorded tool call: {record.get('tool_name')} "
                    f"(success={record.get('success')})"
                )
            except Exception as e:
                logger.error(f"Failed to record tool call: {e}")

    def close_session(
        self,
        session_id: str,
        total_calls: int = 0,
        failed_calls: int = 0,
        tools_used: list[str] | None = None,
    ) -> dict:
        """Finalize a session with statistics.

        Args:
            session_id: Session UUID
            total_calls: Total tool calls in session
            failed_calls: Number of failed tool calls
            tools_used: List of unique tools called

        Returns:
            Updated session data
        """
        session_file = self.sessions_dir / f"{session_id}.json"
        lock = self._get_session_lock(session_id)

        with lock:
            try:
                with open(session_file, "r") as f:
                    session_data = json.load(f)

                # Update stats
                total = total_calls or len(session_data.get("tool_calls", []))
                failed = failed_calls or sum(
                    1
                    for call in session_data.get("tool_calls", [])
                    if not call.get("success", True)
                )
                success_rate = (total - failed) / total if total > 0 else 1.0

                tools_used = tools_used or list(
                    set(
                        call.get("tool_name")
                        for call in session_data.get("tool_calls", [])
                    )
                )

                session_data["ended_at"] = datetime.utcnow().isoformat() + "Z"
                session_data["stats"] = {
                    "total_tool_calls": total,
                    "failed_tool_calls": failed,
                    "success_rate": success_rate,
                    "tools_used": tools_used,
                }

                with open(session_file, "w") as f:
                    json.dump(session_data, f, indent=2)

                logger.debug(
                    f"Session {session_id} closed. "
                    f"Total calls: {total}, Failed: {failed}, "
                    f"Success rate: {success_rate:.1%}"
                )

                return session_data

            except Exception as e:
                logger.error(f"Failed to close session: {e}")
                return {}

    def store_reflection(self, session_id: str, content: str) -> Path:
        """Store a markdown reflection for a session.

        Args:
            session_id: Session UUID
            content: Markdown reflection content

        Returns:
            Path to reflection file
        """
        reflection_file = self.reflections_dir / f"{session_id}.md"

        try:
            with open(reflection_file, "w") as f:
                f.write(content)

            logger.debug(f"Stored reflection for session {session_id}")
            return reflection_file

        except Exception as e:
            logger.error(f"Failed to store reflection: {e}")
            return reflection_file

    def update_memory(
        self, session: dict, reflection: dict | None = None
    ) -> None:
        """Update cross-session memory with aggregated learnings.

        Args:
            session: Session data dict
            reflection: Parsed reflection dict (optional)
        """
        try:
            # Load or initialize memory
            memory = {}
            if self.memory_file.exists():
                with open(self.memory_file, "r") as f:
                    memory = json.load(f)

            # Initialize if needed
            if not memory:
                memory = {
                    "schema_version": 1,
                    "last_updated": datetime.utcnow().isoformat() + "Z",
                    "tool_stats": {},
                    "known_patterns": [],
                    "generated_tools": [],
                    "generated_skills": [],
                }

            # Update tool statistics
            for call in session.get("tool_calls", []):
                tool_name = call.get("tool_name")
                if not tool_name:
                    continue

                if tool_name not in memory["tool_stats"]:
                    memory["tool_stats"][tool_name] = {
                        "call_count": 0,
                        "fail_count": 0,
                        "avg_latency_ms": 0.0,
                        "last_error": None,
                    }

                stats = memory["tool_stats"][tool_name]
                stats["call_count"] += 1
                if not call.get("success", True):
                    stats["fail_count"] += 1
                    stats["last_error"] = call.get("error", "Unknown error")

                # Update average latency (simple moving average)
                latency = call.get("latency_ms", 0)
                old_count = stats["call_count"] - 1
                if old_count > 0:
                    stats["avg_latency_ms"] = (
                        stats["avg_latency_ms"] * old_count + latency
                    ) / stats["call_count"]
                else:
                    stats["avg_latency_ms"] = latency

            # Update timestamp
            memory["last_updated"] = datetime.utcnow().isoformat() + "Z"

            # Write back
            with open(self.memory_file, "w") as f:
                json.dump(memory, f, indent=2)

            logger.debug(f"Updated cross-session memory")

        except Exception as e:
            logger.error(f"Failed to update memory: {e}")

    def get_tool_stats(self, n_sessions: int = 10) -> dict:
        """Get aggregated tool statistics.

        Args:
            n_sessions: Number of recent sessions to analyze

        Returns:
            Tool statistics dict from memory.json
        """
        try:
            if self.memory_file.exists():
                with open(self.memory_file, "r") as f:
                    memory = json.load(f)
                return memory.get("tool_stats", {})
        except Exception as e:
            logger.error(f"Failed to get tool stats: {e}")

        return {}

    def get_recent_reflections(self, n: int = 3) -> list[str]:
        """Get recent reflection markdown files.

        Args:
            n: Number of recent reflections

        Returns:
            List of markdown reflection contents (most recent first)
        """
        try:
            if not self.reflections_dir.exists():
                return []

            reflection_files = sorted(
                self.reflections_dir.glob("*.md"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:n]

            reflections = []
            for file in reflection_files:
                with open(file, "r") as f:
                    reflections.append(f.read())

            logger.debug(f"Loaded {len(reflections)} recent reflections")
            return reflections

        except Exception as e:
            logger.error(f"Failed to get recent reflections: {e}")
            return []

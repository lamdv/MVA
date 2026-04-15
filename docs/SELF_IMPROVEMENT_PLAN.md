# Agent Self-Improvement Feature Plan

**Status:** Approved design, ready for implementation  
**Created:** 2026-04-16  
**Location:** `/home/ldang/.claude/plans/structured-growing-candy.md` (full plan)

## Quick Summary

Add a three-phase self-improvement loop to MVA agents:

1. **Observe** — Telemetry on every tool call (JSON files in `sandbox/telemetry/sessions/`)
2. **Reflect** — Post-session LLM analysis (Markdown reflections in `sandbox/telemetry/reflections/`)
3. **Improve** — Auto-generate new tools and skills from identified gaps

All features are **fully opt-in** via `config.yml`. Without the `self_improvement:` block, zero behavior change.

---

## Architecture

```
stream() / run() loop
    ↓
_execute_tool() [instrumented with telemetry]
    ↓
TelemetryStore (JSON files)
    ↓
_finalize_session() [after loop ends]
    ├─ ReflectionEngine → LLM reflection
    └─ ImprovementEngine → generate tools/skills
```

---

## Key Design Decisions

### Storage: JSON + Markdown (No SQL)

- **Sessions:** `sandbox/telemetry/sessions/<id>.json` — appends tool call records
- **Reflections:** `sandbox/telemetry/reflections/<id>.md` — markdown format
- **Memory:** `sandbox/telemetry/memory.json` — cross-session aggregates
- **Generated:** `sandbox/telemetry/generated_tools/` and `generated_skills/`

### Opt-in via Config

```yaml
# config.yml
self_improvement:
  telemetry_dir: sandbox/telemetry
  reflect_always: true
  fail_rate_threshold: 0.3
  slow_tool_threshold_ms: 5000
```

Without this block → no telemetry, no reflection, no improvement.

### Reflection Format: Markdown Tables

LLM outputs markdown tables (not JSON) for insights — simpler parsing:

```markdown
## Tool Insights
| Tool | Issue | Detail |
|------|-------|--------|
| code_execution | missing | No HTTP GET tool |

## Skill Insights
| Pattern | Action | Name |
|---------|--------|------|
| Fetch APIs | create | http-fetch |
```

### Safe Generation

- Generated tools → `sandbox/telemetry/generated_tools/` (never `tools/`)
- Generated skills → `sandbox/telemetry/generated_skills/` (never `sandbox/engine/skills/`)
- **NO auto-loading** — Tools must be explicitly reviewed and promoted by user
  - User sees generated tools in `/review-tools` CLI command
  - User decides to promote to `tools/` or delete
  - Only promoted tools load on next session
- Reflection uses `agent.complete()` (single LLM call, no tool loop, no recursion)

---

## Files to Create (3 new modules)

### `src/mva/agent/telemetry.py`

`TelemetryStore` class — manages JSON file I/O:

```python
class TelemetryStore:
    def new_session(self, model: str) -> str
    def record_tool_call(self, record: dict) -> None
    def close_session(self, session_id, **counts) -> dict
    def store_reflection(self, session_id: str, content: str) -> Path
    def update_memory(self, session: dict, reflection: dict) -> None
    def get_tool_stats(self, n_sessions: int = 10) -> dict
    def get_recent_reflections(self, n: int = 3) -> list[str]
```

### `src/mva/agent/reflection.py`

`ReflectionEngine` class — post-session LLM reflection:

```python
class ReflectionEngine:
    def maybe_reflect(self, session_record: dict, history: list[dict]) -> str | None
    def reflect(self, session_record: dict, history: list[dict], trigger: str) -> str
    def _build_prompt(self, session_record, tool_stats, past_reflections) -> str
```

Triggers: `reflect_always`, `fail_rate_threshold`, `slow_tool_threshold_ms`

### `src/mva/agent/improvement.py`

`ImprovementEngine` class — tool and skill generation:

```python
class ImprovementEngine:
    def maybe_improve(self, reflection_md: str) -> list[str]
    def generate_tool(self, tool_name: str, detail: str) -> str | None
    def generate_skill(self, pattern: str, new_name: str) -> str | None
```

---

## Files to Modify (4 files, small changes)

### `src/mva/agent/base.py`

1. Add `telemetry_dir: Path | None = None` param to `__init__`
2. Create `TelemetryStore` if `telemetry_dir` is set
3. Wrap `_execute_tool()` with timing + `store.record_tool_call()`
4. Add `_finalize_session(history)` called at end of `stream()` and `run()`
5. Pass `iteration=iteration` from loop counter to `_execute_tool()`

### `src/mva/agent/__init__.py`

1. Read `self_improvement:` from `config.yml`
2. Pass `telemetry_dir` to `Agent.__init__()`
3. Load previously generated tools: `load_tools_from_directory(generated_tools/)`
4. Load previously generated skills: `skills.refresh()` on generated_skills dir

### `src/mva/agent/tools.py`

One-liner bug fix in `load_tools_from_directory()`:

```python
# Prevent duplicate registration
existing_names = {t.name for t in _loaded_tools}
if tool.name not in existing_names:
    _loaded_tools.append(tool)
```

### `config.yml`

Add optional `self_improvement:` section:

```yaml
self_improvement:
  telemetry_dir: sandbox/telemetry
  reflect_always: true
  fail_rate_threshold: 0.3
  slow_tool_threshold_ms: 5000
```

---

## Two New Skills

### `sandbox/engine/skills/reflect/SKILL.md`

Meta-skill for manual reflection on agent performance.

### `sandbox/engine/skills/self-improve/SKILL.md`

Meta-skill for improvement decision-making.

---

## Data Schemas

### `sessions/<id>.json`

```json
{
  "session_id": "uuid",
  "started_at": "ISO8601",
  "ended_at": "ISO8601",
  "model": "claude-3-5-sonnet-20241022",
  "tool_calls": [
    {
      "record_id": "uuid",
      "tool_name": "code_execution",
      "args_repr": "{\"code\": \"...\"}" ,
      "success": false,
      "error": "ModuleNotFoundError: ...",
      "latency_ms": 1240.5,
      "iteration": 0
    }
  ],
  "stats": {
    "total_tool_calls": 2,
    "failed_tool_calls": 1,
    "success_rate": 0.5,
    "tools_used": ["code_execution", "write_file"]
  }
}
```

### `reflections/<id>.md`

```markdown
---
session_id: uuid
created_at: ISO8601
trigger: high_failure_rate
---

## What Happened
[2-4 sentences on what went well/poorly]

## Tool Insights
| Tool | Issue | Detail |
|------|-------|--------|
| code_execution | missing | No HTTP GET tool |

## Skill Insights
| Pattern | Action | Name |
|---------|--------|------|
| Fetch APIs | create | http-fetch |

## Improvements Triggered
- Generated tool: `http_get`
- Created skill: `http-fetch`
```

### `memory.json`

```json
{
  "schema_version": 1,
  "last_updated": "ISO8601",
  "tool_stats": {
    "code_execution": {
      "call_count": 14,
      "fail_count": 3,
      "avg_latency_ms": 820.4,
      "last_error": "ModuleNotFoundError"
    }
  },
  "known_patterns": [
    {
      "pattern_id": "uuid",
      "description": "Fetch data from HTTP APIs",
      "frequency": 2,
      "resolved_by": "http_get"
    }
  ],
  "generated_tools": ["http_get"],
  "generated_skills": ["http-fetch"]
}
```

---

## Implementation Order

1. **telemetry.py** — No MVA deps, pure stdlib + JSON
2. **base.py** — Add param, instrument `_execute_tool`, stub `_finalize_session`
3. **reflection.py** — Depends on TelemetryStore + Agent.complete()
4. **improvement.py** — Depends on reflection output + SkillCatalog
5. **agent/__init__.py** — Wire config, load generated tools/skills
6. **config.yml** — Add opt-in `self_improvement:` block
7. **Two SKILL.md** meta-skills

Also: One-liner fix in `tools.py` (dedup guard).

---

## Example Flow

**User:** "Fetch Bitcoin price and save it to a file"

1. Agent calls `code_execution("import requests...")` → **fails** (no requests in sandbox)
2. `_execute_tool()` records: `{tool_name: "code_execution", success: false, error: "ModuleNotFoundError"}`
3. Agent succeeds with urllib workaround
4. `_finalize_session()` sees `fail_rate = 0.5 > 0.3` → triggers reflection
5. LLM writes reflection identifying `code_execution|missing|No HTTP GET tool`
6. `ImprovementEngine` generates a new `http_get()` tool using stdlib
7. Tool hot-loaded: `sandbox/telemetry/generated_tools/http_get.py`
8. `memory.json` updated with pattern "Fetch APIs" → resolved by `http_get`
9. **Next session:** `http_get` available from start; past reflection injected into context

---

## Testing & Verification

```bash
# Enable in config.yml
uv run mva test "Read files and summarize them"

# Inspect telemetry
cat sandbox/telemetry/sessions/*.json | python -m json.tool

# Inspect reflection
cat sandbox/telemetry/reflections/*.md

# Check memory
cat sandbox/telemetry/memory.json | python -m json.tool

# Verify generated tool loaded
uv run mva list

# Next session
uv run mva chat -v
```

---

## Safety & User Control

### Tool Loading

- **Tools only auto-load from configured `tools/` directory**
- Generated tools isolated in `sandbox/telemetry/generated_tools/`
- **NO auto-loading** of generated tools (Phase 3)
- User explicitly reviews and promotes via `/review-tools` CLI command
- Only promoted tools load on next session

### Non-Breaking Guarantees

- All behavior gated on `self_improvement:` in config.yml
- Generated code in `sandbox/telemetry/`, never in `tools/` or primary `skills/`
- Exceptions in `_finalize_session()` caught and logged — never propagate
- Reflection uses `agent.complete()` (no tool loop, no recursion)
- Dedup fix in `tools.py` is backward-compatible

---

## See Also

- Full plan: `/home/ldang/.claude/plans/structured-growing-candy.md`
- Agent docs: `docs/AGENT.md`
- Tools docs: `docs/TOOLS.md`
- Skills docs: `docs/SKILLS.md`

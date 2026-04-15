# Agent Self-Improvement Implementation

**Status:** In progress (Phase 1: Observe)  
**Started:** 2026-04-16  
**Full plan:** See `docs/SELF_IMPROVEMENT_PLAN.md`

## Quick Start

Enable self-improvement in `config.yml`:

```yaml
self_improvement:
  telemetry_dir: sandbox/telemetry
  reflect_always: true
  fail_rate_threshold: 0.3
  slow_tool_threshold_ms: 5000
```

Then run an agent session:

```bash
uv run mva test "Your task here"
```

Telemetry will be saved to `sandbox/telemetry/`.

---

## Three-Phase Design

### Phase 1: Observe ✓ Planning
- `src/mva/agent/telemetry.py` — TelemetryStore class
- Instrument `_execute_tool()` in base.py
- Record every tool call to JSON files

### Phase 2: Reflect ✓ Complete
- `src/mva/agent/reflection.py` — ReflectionEngine class
- Post-session LLM analysis
- Store reflections as Markdown

### Phase 3: Improve 🔄 Next
- `src/mva/agent/improvement.py` — ImprovementEngine class
- Generate new tools and skills
- Hot-load into running agent

---

## Architecture

```
_execute_tool()  ← instrument with telemetry
    ↓
TelemetryStore  ← records to JSON
    ↓
_finalize_session()  ← at end of stream()/run()
    ├─ ReflectionEngine  ← LLM reflection
    └─ ImprovementEngine ← generate tools/skills
```

---

## Data Storage

```
sandbox/telemetry/
├── sessions/
│   └── <session_id>.json        ← tool calls + stats
├── reflections/
│   └── <session_id>.md          ← markdown reflection
├── memory.json                  ← cross-session learning
├── generated_tools/
│   └── <name>.py                ← tools agent wrote
└── generated_skills/
    └── <name>/SKILL.md          ← skills agent wrote
```

---

## Implementation Phases

### Phase 1: Observe ✓ (COMPLETE)

**Files created:**
- `src/mva/agent/telemetry.py` — TelemetryStore class

**Files modified:**
- `src/mva/agent/base.py` — Added telemetry_dir param, instrumented _execute_tool, added _finalize_session
- `src/mva/agent/__init__.py` — Wired telemetry config (NO auto-loading of generated tools)
- `src/mva/agent/tools.py` — Added dedup guard in load_tools_from_directory
- `config.yml` — Added self_improvement section (opt-in)

**What it does:**
- Records every tool call: name, args, success/fail, latency, errors
- Stores in per-session JSON files (thread-safe)
- Updates cross-session memory.json with aggregated stats
- **SAFETY:** Generated tools do NOT auto-load
  - Tools only load from configured `tools/` directory
  - Generated tools isolated in `sandbox/telemetry/generated_tools/`
  - User explicitly promotes tools via `/review-tools` CLI command

---

### Phase 2: Reflect

**Files to create:**
- `src/mva/agent/reflection.py` — ReflectionEngine class

**What it does:**
- After each session, asks LLM to analyze what worked
- Identifies tool/skill insights using markdown tables
- Stores reflections as readable markdown files
- Injects past reflections into next session

---

### Phase 3: Improve

**Files to create:**
- `src/mva/agent/improvement.py` — ImprovementEngine class

**What it does:**
- Generates new tools for missing capabilities
- Generates new skills for identified patterns
- Hot-loads into running session
- Updates cross-session memory

---

## Session JSON Schema

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
      "args_repr": "{\"code\": \"...\"}",
      "success": false,
      "error": "ModuleNotFoundError: No module named 'requests'",
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

---

## Next Steps

1. Implement `telemetry.py` (TelemetryStore class)
2. Modify `base.py` (add telemetry_dir param, instrument _execute_tool)
3. Test Phase 1 with `uv run mva test "..."`
4. Check `sandbox/telemetry/sessions/*.json` for recorded data
5. Then proceed to Phase 2 (Reflection)

---

## Key Design Points

### Why JSON + Markdown?
- Human-readable
- No SQL dependency
- Easy to inspect and debug
- Markdown reflections are natural for agents to read

### Why Opt-in?
- Zero behavior change without config
- Safe feature for users to enable when ready
- Easy to disable by removing config block

### Why Hot-loading?
- Generated tools/skills available immediately
- No restart required
- Seamless improvement during sessions

### Why Safe?
- Generated code in `sandbox/telemetry/`, never in `tools/`
- Reflection uses `agent.complete()` (no tool loop)
- No recursion possible
- Exceptions caught in _finalize_session

---

## Testing & Verification

Once Phase 1 is implemented:

```bash
# Enable in config.yml
uv run mva test "Read all files and summarize them"

# Check telemetry was captured
cat sandbox/telemetry/sessions/*.json | python -m json.tool

# Verify structure
ls -la sandbox/telemetry/
```

---

## See Also

- Full architecture: `docs/ARCHITECTURE.md`
- Agent API: `docs/AGENT.md`
- Tools system: `docs/TOOLS.md`
- Skills system: `docs/SKILLS.md`
- Configuration: `docs/CONFIGURATION.md`

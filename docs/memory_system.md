# Memory System for MVA

> Design doc — May 2026

---

## Overview

**What problem does this solve?**  
MVA is currently stateless beyond the in-memory `history` list. Every session starts from scratch. The model has no persistent knowledge about the project, the user's preferences, past decisions, or recurring workflows.

**What is memory?**  
A set of layers (data stores + tools) that let MVA persist knowledge *across* conversations, so each session builds on the last rather than starting from blank.

---

## The Five Layers

| Layer | Name | Lifetime | What it stores |
|-------|------|----------|----------------|
| L0 | **Conversation Buffer** | session (in-memory) | Raw `history` — already exists |
| L1 | **Working Memory** | session (persisted to file) | Active task summary, open files, current goals |
| L2 | **Episodic Log** | persistent (append-only) | Per-session summaries: what was done, decisions made |
| L3 | **Semantic Store** | persistent (curated) | Facts, conventions, architecture, preferences |
| L4 | **Procedural Cache** | persistent (learned) | Successful workflow patterns, command recipes |

---

### L0 — Conversation Buffer

Already exists as `history: list[dict[str, Any]]` in `cli.py`. No changes.

---

### L1 — Working Memory

A structured snapshot of *"what am I doing right now?"* that persists across tool calls within a session. The LLM reads and writes it through tools.

**Format** (markdown with YAML frontmatter, stored at `.mva/memory/working.md`):

```yaml
---
session_id: "2026-05-09_abc123"
task: "Implement memory system"
active_files:
  - src/mva/memory/__init__.py
  - src/mva/tools/builtin/memory_read.py
open_questions:
  - "Should we use SQLite or JSON for semantic storage?"
decisions_made:
  - "Use SQLite for semantic, JSONL for episodic"
status: "Design phase"
---
```

**Tools:**
- `working_memory_read()` — return the current working memory text
- `working_memory_update(content: str)` — replace working memory

**Key insight:** Working memory is self-referential. The model is told in the system prompt: *"You have a working memory. Use it to track your current task, open files, and decisions. Update it proactively."*

---

### L2 — Episodic Log

An append-only journal of every session. Each entry is a structured summary generated *at session end* (triggered by `/exit` or a new `/save_session` command).

**Format** (JSONL, stored at `.mva/memory/episodic.jsonl`):

```jsonl
{"session_id": "2026-05-09_abc123", "started": "2026-05-09T10:00:00Z", "ended": "2026-05-09T10:45:00Z", "turns": 12, "tool_calls": 7, "summary": "Designed and documented the memory system architecture.", "key_decisions": [{"decision": "Use SQLite (stdlib) for semantic memory", "rationale": "Zero external dependencies, structured queries"}], "user_preferences": ["Prefers YAML over TOML", "Wants design docs before implementation"]}
```

**Generation:**
- On session close (or `/save_session`), the LLM receives a compact prompt built from `history` and generates a summary.
- Cheap call: `temperature=0.3`, `max_tokens=300`.
- Result is appended to `episodic.jsonl`.

**Tool:**
- `memory_recall_recent(query: str, limit: int = 5)` — search episodic log entries by keyword matching their summary text.

---

### L3 — Semantic Store

A curated knowledge base of facts about the project, the user, and conventions.

**Format** (SQLite, stored at `.mva/memory/semantic.db`):

```sql
CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,        -- "project", "user", "architecture", "convention"
    key TEXT NOT NULL,              -- e.g. "test_framework", "preferred_formatter"
    value TEXT NOT NULL,            -- e.g. "pytest"
    source_session TEXT,            -- session_id that contributed this fact
    confidence REAL DEFAULT 1.0,    -- 0.0 to 1.0
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE facts_tags (
    fact_id INTEGER,
    tag TEXT NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES facts(id)
);
```

**Tools:**
- `memory_store(namespace: str, key: str, value: str, tags: list[str] = [])` — store a fact
- `memory_retrieve(query: str, namespace: str | None = None)` — search facts by key/value/tag
- `memory_forget(key: str)` — remove a fact by key

**Key design choice:** Facts are *explicitly* stored by the LLM during conversation. No automatic embedding or vector search in v1. The model decides what is important enough to remember, and uses descriptive keys so simple `LIKE` queries work well.

---

### L4 — Procedural Cache

Learned, reusable sequences of tool calls that solved a problem before.

**Format** (same SQLite DB, `procedures` table):

```sql
CREATE TABLE procedures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL,
    steps TEXT NOT NULL,             -- JSON array of {tool, args} objects
    created_at TEXT DEFAULT (datetime('now')),
    last_used TEXT,
    use_count INTEGER DEFAULT 0
);
```

**Tools:**
- `procedure_save(name: str, description: str, steps: list[dict])` — save a procedure
- `procedure_run(name: str)` — execute all steps in sequence
- `procedure_list()` — list all saved procedures

**Stretch goal.** Needs careful security review (saved procedures could be dangerous). Phase 4 material.

---

## Directory Layout

```
.mva/memory/                 # project-level memory (tied to CWD)
├── working.md               # L1: working memory
├── episodic.jsonl           # L2: session journal (append-only)
├── semantic.db              # L3+L4: SQLite knowledge store
└── config.yaml              # memory settings (optional)

~/.mva/memory/               # global memory (cross-project)
├── episodic.jsonl
├── semantic.db
└── config.yaml
```

Memory is always scoped. The system prompt tells the model:

> *"You have project memory (`.mva/memory/`) and global memory (`~/.mva/memory/`). Project memory is shared with others who clone this repo. Global memory is yours alone."*

---

## Integration Points

### New files

| File | Purpose |
|------|---------|
| `src/mva/memory/__init__.py` | `MemoryDB` (SQLite), `EpisodicLogger` (JSONL), `WorkingMemory` (read/write markdown) |
| `src/mva/memory/session.py` | `Session` value object, `compress_history()`, `generate_facts()` helpers |

### Modified files

| File | Changes |
|------|---------|
| `src/mva/tools/builtin/__init__.py` | Register memory tools (see table below) |
| `src/mva/cli.py` | Open/close session on start/exit; new `/save`, `/remember`, `/forget` commands |
| `src/mva/utils/__init__.py` | `build_system_prompt()` gains optional `memory_context` parameter; new command dispatch entries |

### New tools

| Tool | Layer | Description |
|------|-------|-------------|
| `memory_store` | L3 | Store a fact in semantic memory |
| `memory_retrieve` | L3 | Query semantic memory |
| `memory_forget` | L3 | Remove a fact |
| `memory_recall_recent` | L2 | Search episodic log |
| `working_memory_read` | L1 | Read current working memory |
| `working_memory_update` | L1 | Write working memory |
| `procedure_save` | L4 | Save a workflow pattern |
| `procedure_run` | L4 | Execute a saved procedure |
| `procedure_list` | L4 | List saved procedures |

### New REPL commands

| Command | Action |
|---------|--------|
| `/save` | Manually trigger episodic summary + fact extraction |
| `/remember` | Show what MVA knows about the project/user (dump semantic store) |
| `/forget <pattern>` | Erase memories matching a key or pattern |

---

## Retrieval Strategy

When building the system prompt, what memories are injected?

| Trigger | What is injected |
|---------|-----------------|
| **Each turn** (automatic) | Working memory (always inline) + semantic facts matching turn intent (keyword match on `key`/`tag`) + last 2–3 episodic summaries |
| **Explicit tool call** | `memory_retrieve(query)` — full SQL `LIKE` search. `memory_recall_recent(query)` — grep on JSONL |

No embeddings or vector DB for v1. If needed later, embedding-based retrieval can be added via a tool that calls the same API used for chat (many providers offer embeddings on the same base URL).

---

## Security Considerations

1. **Project memory is in `.mva/memory/`** — under git (or `.gitignore` if preferred).
2. **Global memory is in `~/.mva/memory/`** — user-only access.
3. **User confirmation** — `memory_store` and `memory_forget` prompt for confirmation before writing/erasing facts (same pattern as file ops).
4. **Episodic logs are never automatically deleted** — but the user can `rm` them directly.
5. **Procedures (L4)** — replaying saved tool calls is inherently dangerous. Must be reviewed carefully before enabling.

---

## Example Flow

```
User: "Let's work on the auth module. Remember, I prefer passlib over bcrypt."

Model (stores fact via tool):
→ memory_store(namespace="user", key="password_library", value="passlib")

Model (updates working memory):
→ working_memory_update(content="task: Add password hashing to auth module\nactive_files: [auth/login.py]")

... (tool calls, edits, bash commands) ...

User: "/exit"
MVA: generates episodic summary → appends to episodic.jsonl
```

Next session, the system prompt automatically includes:

```
Memory context:
- Working memory: task "Add password hashing to auth module"
- Fact: user preference password_library = passlib
- Last session: "Refactored auth/login.py to use passlib"
```

---

## Phasing

| Phase | Layers | Effort | Description |
|-------|--------|--------|-------------|
| **1** | L1 + L3 | ~2 days | Working memory + semantic store as tools. Core memory capability. |
| **2** | L2 | ~1 day | Auto-summarization on `/exit` and `/save`. Episodic continuity. |
| **3** | Context injection | ~1 day | Auto-inject relevant memories into system prompt each turn. |
| **4** | L4 | ~2 days | Procedural cache. Requires careful security review. |

---

## Why This Design Fits MVA

| MVA Principle | How Memory Respects It |
|:---|:---|
| **Minimal dependencies** | SQLite is stdlib. No vector DB, no Redis, no bloat. |
| **Tool-driven** | Memory is just more tools. The model chooses when to remember. |
| **Security-first** | All memory writes go through the same confirmation flow as file writes. |
| **Incremental adoption** | Memory is optional. Without `.mva/memory/`, MVA works exactly as before. |
| **Transparency** | Everything is plain files: `working.md`, `episodic.jsonl`, SQLite. User can `cat`, `grep`, `rm` freely. |

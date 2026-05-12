# CLI Improvement Roadmap

This doc outlines planned improvements to the MVA CLI (`src/mva/cli/`), organized into short-term, medium-term, and long-term buckets. Each item includes rationale, implementation sketch, and effort estimate.

---

## Table of Contents

- [Current State Summary](#current-state-summary)
- [Phase 1 — Short-Term (v2.1–v2.2)](#phase-1--short-term-v21v22)
- [Phase 2 — Medium-Term (v2.3–v2.4)](#phase-2--medium-term-v23v24)
- [Phase 3 — Long-Term (v3.0+)](#phase-3--long-term-v30)
- [Architecture & Cross-Cutting Concerns](#architecture--cross-cutting-concerns)

---

## Completion Status

| # | Item | Status | PR/Notes |
|:---:|---|---|:---|
| 1.1 | Split `utils/` → `agent/_system.py` + `cli/_commands.py` | ✅ **Done** | `utils/__init__.py` deleted |
| 1.2 | Streaming progress spinner | ✅ **Done** | `start_spinner()` / `stop_spinner()` in renderer |
| 1.3 | Non-blocking cancellation UX | ✅ **Done** | Debounce, "Cancelling…" feedback, 2nd press = hard exit |
| 1.4 | Error recovery (strip failed msg from history) | ✅ **Done** | `repl.py` LLMError handler |
| 1.5 | Model validation warning | ✅ **Done** | Warning when no `models` list in config |
| 1.6 | File path tab completion | ✅ **Done** | `MVACompleter` glob fallback |
| 1.7 | `--yes` / `-y` flag | ✅ **Done** | `auto_confirm` through session + CLI flag |
| 2.1 | `--markdown` / `-m` flag | ✅ **Done** | Chunk-based `MarkdownRenderer` |
| 2.2 | Session save/load | ✅ **Done** | `/save`, `/load`, `/sessions`, `/delete` + auto-save on exit |
| 2.3 | Conversation export | ✅ **Done** | `/export` and `/export <file>` commands in `_commands.py` |
| 2.4 | Provider connection test | ✅ **Done** | `/ping` command + auto-test on `/provider` / `/model` switch |
| 2.5 | `/edit` inline editor | ❌ **Dropped** | Out of scope |
| 2.6 | Token usage display | ✅ **Done** | Per-turn `📊` one-liner + toolbar + `/usage` |
| 3.1 | Visual diff in `edit` tool results | ✅ **Done** | `_unified_diff()` in edit tool + `Syntax(diff)` in renderer |

## Current State Summary

The CLI now has clean separation between core and UI layers:

| Module | Lines | Role |
|:---|---:|:---|
| `agent/_system.py` | ~260 | Core: signals, system prompt, message building |
| `cli/_commands.py` | ~490 | CLI: command dispatch, display helpers, hot-reload |
| `cli/app.py` | ~150 | Typer entry point, startup orchestration |
| `cli/repl.py` | ~220 | REPL loop, single-run handler |
| `cli/console.py` | ~305 | prompt-toolkit session, completer, toolbar |
| `cli/renderer.py` | ~355 | Streaming event renderer, Markdown chunk renderer, spinner |

**Resolved pain points:**
- ✅ `utils/` no longer exists — core vs CLI cleanly split
- ✅ Error recovery strips failed message from history
- ✅ Markdown rendering available via `--markdown` flag
- ✅ Progress spinner while waiting for first token
- ✅ Tab completion for file paths
- ✅ `--yes` flag for non-interactive approval
- ✅ Token usage visible in toolbar + per-turn + `/usage` command

**Remaining pain points:**
1. No provider connection test on switch
2. No plugin system
3. No multi-line input editor

---

## Phase 1 — Short-Term (v2.1–v2.2) ✅ **Completed**

All Phase 1 items have been implemented. See the [Completion Status](#completion-status) table above.

---

### 1.2 Streaming Progress Indicator

**Problem:** During streaming, the terminal is silent until the first token arrives. For slow models, users don't know if the request is being processed.

**Solution:** Show an animated spinner in the bottom-right corner while waiting for the first streaming delta. Hide it once content starts flowing.

```python
# In renderer.py (or a new progress module)
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
)

_spinner: Progress | None = None

def start_spinner() -> None:
    global _spinner
    _spinner = Progress(
        SpinnerColumn(),
        TextColumn("[dim]{task.description}[/]"),
        TimeElapsedColumn(),
        console=_console,
    )
    _spinner.add_task("Waiting for response…", total=None)

def stop_spinner() -> None:
    global _spinner
    if _spinner:
        _spinner.stop()
        _spinner = None
```

**Integration point:** Call `start_spinner()` before `session.chat()` in the REPL loop, and `stop_spinner()` on the first `thinking` or `delta` event.

**Effort:** 1 hour.

---

### 1.3 Non-blocking Cancellation UX

**Problem:** Ctrl+C during streaming cancels the current request but gives no visual feedback until the next prompt. Users sometimes hit Ctrl+C multiple times thinking it didn't register.

**Solution:** 
- Show a `[dim](cancelling…)[/]` overlay immediately on first Ctrl+C
- Debounce repeated Ctrl+C presses (within 2 seconds, treat as single cancel)
- A second Ctrl+C within the debounce window → hard exit

**Effort:** 1 hour.

---

### 1.4 Error Recovery in REPL Loop

**Problem:** When an API call fails (network error, 500, timeout), the raw exception propagates to the user as a red `[red]Error:[/] ...` message. The conversation history is **not** cleaned up — the failed user message stays in history, which can confuse the model on retry.

**Solution:** On `LLMError`, strip the last user message from history and optionally show a retry prompt:

```python
# In repl.py
except LLMError as exc:
    _console.print(f"\n[red]Error:[/] {exc}")
    # Remove the failed user message from history
    if session.history and session.history[-1]["role"] == "user":
        session.history.pop()
    # Offer retry
    _console.print("[dim]Message discarded. You can re-type it or try something else.[/]")
    continue
```

**Effort:** 30 minutes.

---

### 1.5 `/model` Provider Validation

**Problem:** `/model <name>` blindly accepts any model name. If the model doesn't exist on the server, the error surfaces only on the next API call.

**Solution:** When the provider declares a `models:` list in config, validate against it immediately. When no list is defined, emit a warning but allow the switch (backward compatible).

Already partially implemented — just need to add the warning:

```python
# In _switch_model(), after setting model without validation:
if not session.available_models:
    _console.print(
        "[yellow]Warning:[/] No models list defined for this provider. "
        "The model may not exist on the server."
    )
```

**Effort:** 20 minutes.

---

### 1.6 Command Completion for File Paths

**Problem:** Tab completion works for commands and model names but not for file paths in message input (e.g. when typing "read src/mva/cli/repl.py" you'd want tab to complete the path).

**Solution:** Add a `PathCompleter` fallback in `MVACompleter` that fires when the input doesn't start with `/`:

```python
# In console.py MVACompleter
import glob

def _complete_path(text: str) -> list[Completion]:
    """Complete file paths relative to CWD."""
    # Find the last word (potential path)
    last_word = text.split()[-1] if text else ""
    if not last_word or not last_word.strip():
        return []
    expanded = glob.glob(f"{last_word}*") + glob.glob(f"{last_word}*/")
    for path in sorted(set(expanded)):
        display = path
        if os.path.isdir(os.path.expanduser(path)):
            display += "/"
        yield Completion(
            display,
            start_position=-len(last_word),
            display=display,
            display_meta="file" if os.path.isfile(path) else "directory",
        )
```

**Effort:** 1 hour.

---

### 1.7 `--yes` / `--no-confirm` Flag for Non-Interactive Mode

**Problem:** `mva "do something dangerous"` auto-denies confirmation prompts. There's no way to say "yes, I trust the model" in non-interactive mode.

**Solution:** Add `--yes` / `-y` flag that auto-approves security confirmations:

```python
@_app.command()
def app(
    ...,
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Auto-approve security confirmations (use with caution).",
    ),
) -> None:
```

Then pass `auto_confirm=yes` to Session instead of `print_mode`.

**Effort:** 30 minutes.

---

Total Phase 1 effort: ~6–7 hours.

---

## Phase 2 — Medium-Term (v2.3–v2.4)

### 2.1 Live Markdown Rendering ✅ **Done**

**Implemented as:** `--markdown` / `-m` CLI flag with chunk-based `MarkdownRenderer` in `renderer.py`. Buffers deltas and flushes at sentence boundaries (`. `), blank lines (`\n\n`), and code fence closures.

**Effort:** 3–4 hours (design + edge-case handling for mid-stream code fences).

---

### 2.2 Session Save/Load

**Problem:** Exiting MVA loses the conversation. There's no way to resume a session later or share it.

**Solution:** Add `/save <name>` and `/load <name>` commands that serialize/deserialize conversation history to JSON files.

```python
_SESSION_DIR = Path.home() / ".config" / "mva" / "sessions"

def _save_session(history: list[dict], name: str) -> None:
    """Save conversation history to ~/.config/mva/sessions/<name>.json."""
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = _SESSION_DIR / f"{name}.json"
    data = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "provider": session.current_provider,
        "model": session.client.default_model,
        "history": history,
    }
    path.write_text(json.dumps(data, indent=2))
    _console.print(f"[green]Session saved as '{name}' ({len(history)} turns).[/]")

def _load_session(session: Session, name: str) -> bool:
    """Load and restore conversation history."""
    path = _SESSION_DIR / f"{name}.json"
    if not path.exists():
        _console.print(f"[yellow]No saved session '{name}'.[/]")
        return False
    data = json.loads(path.read_text())
    session.history = data["history"]
    # Optionally restore provider/model
    if data.get("provider"):
        session.switch_provider(data["provider"])
    if data.get("model"):
        session.set_model(data["model"])
    _console.print(f"[green]Session '{name}' loaded ({len(data['history'])} turns).[/]")
    return True
```

Commands:
- `/save <name>` — save to `~/.config/mva/sessions/<name>.json`
- `/load <name>` — load and restore
- `/sessions` — list saved sessions
- `/delete <name>` — delete a saved session

**Effort:** 2 hours.

---

### 2.3 Conversation Export

**Problem:** No way to export a conversation as Markdown or text for sharing.

**Solution:** Add `/export` and `/export <file>` commands.

```python
def _export_history(history: list[dict], path: str | None = None) -> None:
    """Export conversation as Markdown."""
    lines = ["# MVA Conversation\n"]
    for turn in history:
        role = turn["role"].upper()
        content = turn.get("content", "")
        if turn.get("tool_calls"):
            for tc in turn["tool_calls"]:
                lines.append(f"### 🔧 Tool Call: {tc['function']['name']}\n")
                lines.append(f"```json\n{tc['function']['arguments']}\n```\n")
        if content:
            prefix = "**You:**" if role == "USER" else "**Assistant:**"
            lines.append(f"{prefix}\n\n{content}\n")
    
    output = "\n".join(lines)
    if path:
        Path(path).write_text(output)
        _console.print(f"[green]Exported to {path}[/]")
    else:
        # Print to stdout (for piping)
        print(output)
```

**Effort:** 1 hour.

---

### 2.4 Provider Connection Test

**Problem:** After `/provider <name>`, there's no validation that the provider actually works. The first error surfaces on the next user message.

**Solution:** Add a quick health-check after provider switch:

```python
def _test_provider_connection(session: Session) -> bool:
    """Send a minimal request to verify the provider is reachable."""
    try:
        from mva.agent.types import ChatMessage
        for _ in session.client.chat_stream(
            [ChatMessage(role="user", content="ping")],
            max_tokens=1,
        ):
            break
        return True
    except Exception as exc:
        return False
```

On `/provider <name>`, show `[green]✓ Connection OK[/]` or `[red]✗ Connection failed: {error}[/]`.

**Effort:** 1 hour.

---

### 2.5 `/edit` Command for Inline File Editing ❌ **Dropped**

Out of scope. The model's `edit` tool covers search-and-replace, and users can always use an external editor.

---

### 2.6 Token Usage Display ✅ **Done**

**Implemented as:**
- Per-turn `📊 120↑ 45↓ 165∑` one-liner in `renderer.py` (shown after each response)
- Cumulative token count in the prompt-toolkit **bottom toolbar** (persistent across turns)
- `/usage` command showing a session total table in `_commands.py`

**Effort:** 1 hour.

---

**Phase 2 — All items completed** ✅  
2.1 (Markdown), 2.2 (Session save/load), 2.3 (Export), 2.4 (Connection test), 2.6 (Token usage)  
2.5 dropped — out of scope

---

## Phase 3 — Long-Term (v3.0+)

### 3.1 Visual Diff in `edit` Tool Results ✅ **Done**

Already implemented:
- `edit.py` generates unified diffs via `_unified_diff()` and includes them in `ToolResult`
- `renderer.py` `_render_tool_result()` detects `\nDiff:\n` sections and renders them with `rich.syntax.Syntax(diff_text, "diff", theme="ansi_dark")`
- Same logic in `repl.py` `_run_single()` for non-interactive mode

---

### 3.2 REPL Plugins / Hooks

**Problem:** Extending the REPL (custom prompts, pre/post-processing hooks, event listeners) currently requires modifying `repl.py` directly.

**Solution:** Define a plugin interface that can tap into the REPL lifecycle:

```python
# Plugin hook points
class REPLPlugin:
    def on_startup(self, session: Session, console: Console) -> None: ...
    def on_pre_prompt(self) -> str | None: ...  # return custom prompt text
    def on_pre_message(self, raw: str) -> str: ...  # transform input
    def on_event(self, event: dict) -> None: ...  # tap into events
    def on_shutdown(self) -> None: ...
```

Plugins discovered via `mva.repl_plugins` entry point group or `.mva/plugins/` directory.

**Use cases:** custom pre-prompts, input validation, logging middleware, external integrations.

**Effort:** 4 hours.

---

### 3.3 Tab-Completion for Bash/LS Results

**Problem:** After listing files with `ls` or `list_files`, subsequent tab completion doesn't know about those paths.

**Solution:** Maintain a lightweight file cache that the completer can query:

```python
class FileCache:
    """LRU cache of recently seen file paths, populated by tool results."""
    def __init__(self, maxsize: int = 1000):
        self._paths: dict[str, float] = {}
        self._maxsize = maxsize

    def add(self, path: str) -> None:
        self._paths[path] = time.time()

    def complete(self, prefix: str) -> list[str]:
        return [p for p in self._paths if p.startswith(prefix)]
```

The renderer calls `file_cache.add()` on `list_files` and `read` tool results. The completer queries it alongside filesystem glob.

**Effort:** 2 hours.

---

### 3.4 Multi-Line Input Editor

**Problem:** The REPL currently supports single-line input only. Writing multi-line messages (pasting code, composing long instructions) is awkward.

**Solution:** Add a toggle between single-line and multi-line modes:

- `/multi` — enter multi-line mode (shows a full-screen buffer with prompt_toolkit)
- Ctrl+D or `/end` — submit the multi-line buffer
- `/single` — back to single-line mode

In multi-line mode, show a `[dim](Ctrl+D to send, /end to finish)[/]` hint in the toolbar.

```python
def _multi_line_prompt(pt_session: PromptSession) -> str:
    """Multi-line input using prompt_toolkit's buffered input."""
    _console.print("[dim](Enter message, Ctrl+D or /end on its own line to submit)[/]")
    lines = []
    try:
        while True:
            line = pt_session.prompt("... ", multiline=False)
            if line.strip() == "/end":
                break
            lines.append(line)
    except (EOFError, KeyboardInterrupt):
        pass
    return "\n".join(lines)
```

**Effort:** 2 hours.

---

### 3.5 Rich Configuration Dialogs

**Problem:** Editing `model.yaml` directly is error-prone. Adding a new provider requires knowing the exact YAML format.

**Solution:** Interactive configuration commands:

- `/config providers` — list providers with YAML preview
- `/config add provider` — interactive wizard (name, base_url, api_key, model)
- `/config remove <provider>` — remove a provider
- `/config edit` — open model.yaml in `$EDITOR`

```python
def _add_provider_wizard() -> None:
    """Interactive wizard for adding a new provider."""
    name = typer.prompt("Provider name")
    base_url = typer.prompt("Base URL", default="http://127.0.0.1:8002/v1")
    api_key = typer.prompt("API key", default="no-key", hide_input=False)
    model = typer.prompt("Default model", default="gpt-4o")
    timeout = typer.prompt("Timeout (seconds)", default=120)
    
    # Read, modify, write model.yaml
    ...
```

**Effort:** 3 hours.

---

Total Phase 3 effort: ~11 hours (estimates; 3.1 ✅ done, removes ~2h).

---

## Architecture & Cross-Cutting Concerns

### Monorepo Dependency

The monorepo split ([v2.1 plan](v2.1_monorepo_plan.md)) is a prerequisite for all cleanup-focused improvements (1.1, 1.3, 1.4). New features (1.2, 2.x, 3.x) can be built on top of either structure but benefit from the cleaner separation.

### Dependencies to Add

| Feature | New Dependency | Rationale |
|:---|---:|:---|
| 1.2 Progress spinner | `rich` (already present) | No new deps |
| 2.1 Markdown rendering | `rich.markdown` (already present) | No new deps |
| 2.2 Session save/load | stdlib | No new deps |
| 3.4 Multi-line editor | `prompt-toolkit` (already present) | No new deps |

All improvements use **zero new external dependencies**.

### Risk Register

| Risk | Likelihood | Mitigation |
|:---|---:|:---|
| Markdown rendering breaks on malformed mid-stream content | Medium | Render buffered chunks only at sentence boundaries; fall back to plain text |
| Session save/load conflicts with schema changes | Low | Version the JSON schema; provide migration on load |
| Plugin system scope creep | Medium | Start with minimal hook points; add more on demand |
| Configuration wizard edits wrong `model.yaml` | Low | Always backup before write; show diff before applying |

---

## Appendix: Quick-Win Ordering

If you only have a few hours, implement in this order:

1. ✅ [1.1] Monorepo split (prerequisite for clean code)
2. ✅ [1.4] Error recovery (strip failed message from history)
3. ✅ [1.2] Progress spinner (user-visible win, low effort)
4. ✅ [1.5] Model validation warning
5. ✅ [1.6] File path tab completion
6. ✅ [2.6] Token usage display
7. ✅ [2.2] Session save/load
8. ✅ [2.3] Conversation export
9. ✅ [3.1] Visual diff in `edit` tool results

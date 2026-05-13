# New CLI Design — Readline-based REPL

## Why the prompt-toolkit plan failed

The `docs/cli_improvements.md` plan was fully implemented, but the architecture is
fundamentally flawed. The core problem is **prompt-toolkit's multi-line input**
(item 3.4 — double-Enter submit):

1. **Double-Enter is undiscoverable** — users instinctively press Enter once and
   nothing happens. They don't know they need a blank line to submit.
2. **Non-standard** — every other chat UI (ChatGPT, Claude, Slack, Discord) uses
   single Enter with Shift+Enter for newlines.
3. **Complex key-binding logic** — ~30 lines of fragile `Enter` handler that checks
   buffer state. This breaks when the user pastes multi-line content.
4. **Globals everywhere** — `_session_ref`, `_skills_ref`, `_plugin_manager_ref`,
   `_renderer`, `_spinner`, `_last_model_context` — all module-level mutable state
   that creates hidden coupling.
5. **Two competing input systems** — `repl.py` uses `PromptSession` (minimal
   prompt-toolkit), while `tui.py` uses a full-screen `Application` (two-pane TUI).
   Both have their own key binding logic, both are fragile.
6. **Heavy dependency** — prompt-toolkit is ~15k lines for what amounts to a
   readline loop with tab completion.

---

## New architecture: Readline-backed REPL

### Core design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Input library | Python's `readline` module | Built-in, no deps, handles history + tab completion |
| Submit gesture | **Single Enter** always | Standard, discoverable, no special key bindings |
| Multi-line input | `\` line continuation | Simple, visible, no hidden state |
| History | `readline` history file | Built-in, Ctrl+R search, persistent |
| Tab completion | `readline.set_completer()` | Built-in, simpler than prompt-toolkit `Completer` class |
| Screen management | **No TUI mode** — just print to stdout | Eliminates `tui.py` entirely |
| State management | **No globals** — pass session explicitly | Eliminates hidden coupling |
| Rendering | Print character-by-character (plain text) or Markdown | Same as current, but simpler |
| Plugins | **Removed** — never used, adds complexity | Simplicity over extensibility |
| Markdown mode | Command-line flag `-m` or `/markdown` toggle | Keeps option, simplified implementation |

### File layout (post-cleanup)

```
cli/
├── __init__.py          # empty
├── app.py               # Typer entry point (simplified)
├── repl.py              # The core REPL loop (~100 lines)
├── renderer.py          # Streaming renderer (simplified, ~100 lines)
├── commands.py          # Command dispatch (moved from _commands.py, ~300 lines)
└── completer.py         # readline tab completer (~80 lines)

Removed:
├── console.py           # Deleted — no longer needed
├── plugins/             # Deleted — removed
├── tui.py               # Deleted — no longer needed
```

### REPL loop pseudocode

```python
def repl(session, skills):
    """Simple read-eval-print loop — no prompt-toolkit, no globals."""

    # --- Setup readline ---
    import readline
    histfile = Path.home() / ".config" / "mva" / "history"
    histfile.parent.mkdir(parents=True, exist_ok=True)
    readline.read_history_file(str(histfile))
    readline.set_completer(create_completer(session, skills))
    readline.parse_and_bind("tab: complete")

    # --- Main loop ---
    while True:
        try:
            raw = _read_multiline("You: ")
        except (EOFError, KeyboardInterrupt):
            _save_session_on_exit(session)
            print("\nGoodbye!")
            break

        raw = raw.strip()
        if not raw:
            continue

        # Commands
        if raw.startswith("/"):
            result = handle_command(raw, session, skills)
            if result is False:  # exit
                _save_session_on_exit(session)
                break
            if result == RELOAD_SENTINEL:
                reload_environment(session, skills)
                continue
            continue

        # Streaming response
        print_status_line(session)

        try:
            for event in session.chat(raw):
                render_event(event)
        except LLMError as exc:
            print(f"\n[red]Error:[/] {exc}")
            # Strip failed user message
            if session.history and session.history[-1]["role"] == "user":
                session.history.pop()
            continue

        print()

    # --- Save history ---
    readline.write_history_file(str(histfile))
```

### Multi-line input: `\` continuation

```python
def _read_multiline(prompt: str) -> str:
    """Read input with ``\\`` line continuation.

    Single Enter → submit.
    Line ending with ``\\`` → prompt for next line.
    """
    lines: list[str] = []
    while True:
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            if lines:
                raise  # propagate up
            raise

        # Line continuation: trailing backslash
        if line.endswith("\\") and not line.endswith("\\\\"):
            lines.append(line[:-1])
            prompt = "  ... "  # continuation prompt
            continue

        lines.append(line)
        break

    return "\n".join(lines)
```

This is much simpler than double-Enter. The `\` is:
- **Visible** — the user can see they're in continuation mode
- **Predictable** — always works the same way
- **Standard** — borrowed from bash/sh line continuation

Alternatively, we could support a `/multi` toggle that switches to
double-Enter mode for pasting multi-line blocks, but the `\` approach
covers 95% of use cases with zero mode-switching.

### Tab completion

```python
def create_completer(session, skills):
    """Return a readline completer function."""
    import readline

    # Pre-compute command list
    COMMANDS = [
        "/exit", "/quit", "/clear", "/reset", "/help",
        "/history", "/model", "/provider", "/tools", "/skills",
        "/save", "/load", "/sessions", "/delete", "/export",
        "/usage", "/ping", "/reload", "/markdown",
    ]

    def completer(text: str, state: int) -> str | None:
        # Cursor at start of line → complete commands
        if readline.get_line_buffer().startswith("/"):
            options = [c for c in COMMANDS if c.startswith(text)]
            return options[state] if state < len(options) else None

        # Otherwise → complete file paths
        import glob
        matches = sorted(glob.glob(f"{text}*"))
        if state < len(matches):
            return matches[state]
        return None

    return completer
```

This replaces the 200+ line `MVACompleter` with ~25 lines.

### Status line

Instead of a dynamic toolbar (which requires prompt-toolkit's `Application`),
show a compact status line **after every response**:

```
⚡ provider/model  │  📊 1.2K↑ 800↓ 2K∑
```

And as a subtle hint in the prompt: `[provider/model] You: `

### Streaming renderer (simplified)

The renderer loses the `MarkdownRenderer` class and the spinner. Markdown is
rendered by printing chunks through `rich.markdown.Markdown` at sentence/paragraph
boundaries when `--markdown` is on.

```python
def render_event(event: dict) -> None:
    """Print a session event to the console."""
    t = event["type"]
    if t == "thinking":
        print(f"\033[3m{event['content']}\033[0m", end="", flush=True)
    elif t == "delta":
        print(event["content"], end="", flush=True)
    elif t == "tool_call":
        print(f"\n  ⚡ {event['name']}")
        print(f"    args: {json.dumps(event['args'])[:200]}")
    elif t == "tool_result":
        preview = event["content"][:120].replace("\n", " ")
        if event["is_error"]:
            print(f"  ✗ {preview}")
        else:
            print(f"  ✓ {preview}")
    elif t == "done":
        usage = event.get("usage")
        if usage:
            print(f"\n📊 {usage['prompt_tokens']}↑ {usage['completion_tokens']}↓ {usage['total_tokens']}∑")
```

---

## Migration plan

### Phase 1 — Strip (remove complexity)

| Action | Files affected |
|--------|---------------|
| Remove `cli/plugins/` directory | `cli/plugins/__init__.py`, plugin discovery |
| Remove `cli/tui.py` | — |
| Remove `cli/console.py` | — |
| Remove `_plugin_manager_ref` from `_commands.py` | `cli/_commands.py` |
| Remove plugin hooks from `repl.py` | `cli/repl.py` |
| Remove `set_skills()`, `set_session()`, `_session_ref` from console | `cli/console.py` |

### Phase 2 — Build

| Action | Files affected |
|--------|---------------|
| Create `cli/completer.py` — readline completer | New file |
| Rewrite `cli/repl.py` — readline-based REPL | Full rewrite (~100 lines) |
| Simplify `cli/renderer.py` — remove spinner, simplify Markdown | Edit |
| Move `_commands.py` → `commands.py` | Rename + strip plugin refs |
| Simplify `cli/app.py` — remove prompt-toolkit setup, plugins | Edit |
| Remove `cli/plugins/`, `cli/console.py`, `cli/tui.py` | Deleted |

### Phase 3 — Polish

| Action | Detail |
|--------|--------|
| Test on macOS, Linux | readline behaves differently on each |
| Test piped stdin | `echo "hello" \| mva` |
| Test multi-line via `\` | Edge cases: `\\`, empty continuation |
| Test `/export` | Still works without plugins |
| Update AGENT.md | Remove references to old CLI architecture |

---

## Summary

| Metric | Current (prompt-toolkit) | Proposed (readline) |
|--------|--------------------------|---------------------|
| Input deps | prompt-toolkit | stdlib `readline` |
| Input complexity | ~350 lines (console.py) | ~60 lines (in repl.py + completer.py) |
| Submit gesture | Double-Enter | Single Enter |
| Multi-line | Implicit (double-Enter) | Explicit (`\` continuation) |
| Globals | 6+ module-level refs | Zero |
| Plugin system | 4-file plugin framework | Removed |
| TUI code | 2 parallel input systems | Single code path |
| Tab completion | 200-line `MVACompleter` | 25-line readline callback |
| State management | Globals + setters | Pass session as parameter |
| Terminal compatibility | Requires VT escape codes | Works on any terminal |

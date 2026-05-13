# Async Input & Steering — Architecture & Upgrade Plan

> **Goal:** Allow the user to queue input and issue steering commands *while* the model is responding. No more waiting for the model to finish before you can type the next message or course-correct mid-generation.

---

## Table of Contents

1. [Current Architecture (Why It Blocks)](#1-current-architecture-why-it-blocks)
2. [Design Goals & Constraints](#2-design-goals--constraints)
3. [Proposed Architecture: Threaded Agent with Event Bus](#3-proposed-architecture-threaded-agent-with-event-bus)
4. [Phase 1: Input Queuing During Streaming](#4-phase-1-input-queuing-during-streaming)
5. [Phase 2: Steering Mid-Generation](#5-phase-2-steering-mid-generation)
6. [Phase 3: UI Enhancements (Split Pane, Input Preview)](#6-phase-3-ui-enhancements-split-pane-input-preview)
7. [File-by-File Implementation Guide](#7-file-by-file-implementation-guide)
8. [Timeline & Effort Summary](#8-timeline--effort-summary)
9. [Risk Register](#9-risk-register)

---

## 1. Current Architecture (Why It Blocks)

### The Synchronous Bottleneck

```
REPL Thread (single-threaded, synchronous):

  1. pt_session.prompt()           ← BLOCKS until user presses Enter
  2. session.chat(user_message)    ← BLOCKS until model finishes (all tool rounds)
       │
       ├─ client.chat_stream()     ← Generator, but called in a for-loop
       │    └─ for event in gen:   ← Each iteration yields, but the generator
       │         render(event)       keeps running — no pause point for input
       │
       └─ (returns to prompt)      ← User can finally type again
```

**Key observation:** Even though `session.chat()` is a generator and yields events one at a time, the REPL is still **synchronous within a single thread**. The `for event in session.chat():` loop runs uninterrupted until the model finishes. There is **no point** during model generation where the REPL checks for user input.

### What Happens When the User Types During Streaming

| Action | Current Behavior |
|:---|---|
| User types text while model responds | Characters appear in the terminal (mixed with model output), then are lost when Enter is pressed mid-stream |
| User presses Enter during streaming | `input()` returns unexpectedly — the line goes to whoever called `input()` last, corrupting the UI |
| User presses Ctrl+C | Cancels the current stream (intentional, but only escape hatch) |
| User tries to `/command` while model responds | No effect — `/command` handling only happens at the prompt |

### The Ctrl+C Escape Hatch

The only way to interrupt the model today is Ctrl+C, which:
1. Sets `_cancel_requested = True`
2. The client's `_iter_sse_chunks()` loop checks this flag between chunks
3. Breaks streaming, yields `finish_reason="cancelled"`
4. Session records partial response and returns
5. REPL shows prompt again

This works but is **one-dimensional**: cancel or don't cancel. There's no way to say "good point, but also look at X file" or "stop that approach and try Y instead."

---

## 2. Design Goals & Constraints

### Goals

| # | Goal | Description |
|:---:|:---|---|
| G1 | **Queue input during streaming** | User types a message while model is responding. Message is queued and automatically sent as the next user turn when the model finishes. |
| G2 | **Steer mid-generation** | User sends a steering message that interrupts the current generation, preserves partial output, and injects the steering message as the next input. |
| G3 | **Zero external dependencies** | Use only stdlib (`threading`, `queue`) + already-present deps (`prompt-toolkit`, `rich`). |
| G4 | **Backward compatible** | Existing `Session` API (`session.chat()` generator) must continue to work unchanged. |
| G5 | **Graceful degradation** | If async input is unavailable (e.g., non-TTY mode), fall back to synchronous behavior. |
| G6 | **Non-blocking REPL** | The REPL must never block on `input()` or `prompt()` while the agent is running. |

### Non-Goals

| # | Non-Goal | Rationale |
|:---:|---|---|
| N1 | Full `asyncio` rewrite | Too invasive; every layer (client, session, renderer) would need async conversion. Threads achieve the same UX with 1/5 the code. |
| N2 | True parallel I/O | The model output and user input are multiplexed onto one terminal — true parallelism buys nothing. |
| N3 | Push notifications | No server-side push; the "async" here is terminal I/O only. |

---

## 3. Proposed Architecture: Threaded Agent with Event Bus

### Thread Model

```
┌──────────────────────────────────────────────────────────────────┐
│                         REPL Thread (Main)                        │
│                                                                   │
│  Reads from stdin                                                 │
│  Renders to terminal                                              │
│  Owns prompt-toolkit session                                      │
│  Runs the high-level REPL loop                                    │
│                                                                   │
│  ┌─────────────────────┐   ┌──────────────────────┐              │
│  │  Input Queue        │   │  Event Queue          │              │
│  │  (user → agent)     │   │  (agent → repl)       │              │
│  │  queue.Queue[str]   │   │  queue.Queue[dict]    │              │
│  └─────────┬───────────┘   └──────────┬─────────────┘              │
│            │                          │                            │
└────────────┼──────────────────────────┼────────────────────────────┘
             │                          │
             ▼                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Agent Thread (Worker)                        │
│                                                                   │
│  Runs session.chat() in a background thread                       │
│  Puts events onto the event_queue                                 │
│  Checks input_queue between events + between SSE chunks           │
│  Handles steering interrupts                                      │
│                                                                   │
│  for event in session.chat(msg):                                  │
│      event_queue.put(event)                                       │
│      check_input_queue()  ← steering messages                     │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Queues

| Queue | Type | Direction | Purpose |
|:---|---:|:---:|:---|
| `input_queue` | `queue.Queue[str]` | User → Agent | Regular queued messages and steering commands |
| `event_queue` | `queue.Queue[dict \| _Sentinel]` | Agent → REPL | Streaming events + DONE sentinel |
| `control_queue` | `queue.Queue[str]` | REPL → Agent | Control signals: `"cancel"`, `"steer"` |

### Lifecycle of One Turn

```
REPL Thread                          Agent Thread
────────────                          ────────────
start_agent(msg) ──────────────────►  session.chat(msg)
                                      for event in stream:
loop:                                  event_queue.put(event)
  event = event_queue.get()            
  render(event)                          
  if event["type"] == DONE:           event_queue.put(SENTINEL)
      break                          
                                      ── thread exits ──

# Check for queued input
if not input_queue.empty():
    next_msg = input_queue.get()
    goto start_agent(next_msg)
else:
    show_prompt()
```

### How `Session.chat()` Stays Pure

We do **not** modify `Session` to know about threads. Instead, we create a new class **`AsyncSession`** that wraps a `Session` and runs it on a worker thread:

```python
class AsyncSession:
    """Threaded wrapper around Session. Keeps Session pure."""

    def __init__(self, session: Session):
        self._session = session
        self.input_queue: queue.Queue[str] = queue.Queue()
        self.event_queue: queue.Queue[dict | _Sentinel] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._steer_callback: Callable[[str], None] | None = None

    def start(self, user_message: str) -> None:
        """Start a new turn on the worker thread."""
        self._thread = threading.Thread(
            target=self._run,
            args=(user_message,),
            daemon=True,
        )
        self._thread.start()

    def _run(self, user_message: str) -> None:
        """Worker thread: run session.chat, push events to queue."""
        # We inject a "steering check" callback that Session calls
        # between events and between SSE chunks.
        try:
            for event in self._session.chat(
                user_message,
                _steer_callback=self._check_steer,
            ):
                self.event_queue.put(event)
                # Check for steer *between* events too
                steer_msg = self._check_steer()
                if steer_msg:
                    # Session needs to handle the interrupt
                    # through the steer callback
                    break
        except _SteeringInterrupt as exc:
            self.event_queue.put({
                "type": "steered",
                "prev_content": exc.partial_content,
                "steer_message": exc.steer_message,
            })
        finally:
            self.event_queue.put(_SENTINEL)
```

---

## 4. Phase 1: Input Queuing During Streaming

### What the User Sees

```
Assistant: Let me analyze the code in src/mva/cli/repl.py…
           (streaming output appears line by line)

           ┌─ Input Queue Preview ─────────────────────────┐
           │ [Q] 1: also check the session.py file          │
           └────────────────────────────────────────────────┘

…the model finishes its analysis…

Automatically sending queued message: "also check the session.py file"

You:
```

### Implementation

#### 4.1 `InputCollector` — Non-Blocking Stdin Reader

Wraps `prompt-toolkit`'s ability to **asynchronously read input**. Instead of a blocking `pt_session.prompt()`, we use prompt-toolkit's `Application` API which can be run in the background.

```python
class InputCollector:
    """Non-blocking input collector that queues user input during streaming.

    Uses prompt-toolkit's ``Application`` running on a background thread
    to accept input without blocking the main REPL loop.
    """

    def __init__(self, session: PromptSession):
        self._session = session
        self.queue: queue.Queue[str] = queue.Queue()
        self._running = False
        self._app: Application | None = None

    def start(self) -> None:
        """Start accepting input in the background."""
        self._running = True
        # Create a mini Application that reads one line of input
        # and puts it on the queue
        ...

    def stop(self) -> None:
        self._running = False
        if self._app:
            self._app.exit()

    def read_queued(self) -> list[str]:
        """Drain all queued input (non-blocking)."""
        items = []
        while not self.queue.empty():
            items.append(self.queue.get_nowait())
        return items
```

**Alternative (simpler):** Use `sys.stdin` with `select.poll()` for non-blocking reads in TTY mode. This avoids prompt-toolkit's complexity but loses rich input editing (history, completion).

**Recommended approach:** Build a **mini buffer** using prompt-toolkit's `TextArea` in a separate `Application` instance that writes to a file descriptor or queue. OR even simpler: use `prompt_toolkit.input.create_input()` for non-blocking input.

#### 4.2 `InputPreview` — Display Queued Messages

A `rich.layout.Layout` or fixed-position panel that shows queued messages at the bottom of the terminal, above the prompt line.

```python
class InputPreview:
    """Shows queued input items as a compact panel."""

    def __init__(self):
        self._queued: list[str] = []

    def update(self, items: list[str]) -> None:
        self._queued = items

    def render(self) -> Panel | None:
        if not self._queued:
            return None
        lines = [
            f"[dim][Q] {i+1}: {msg[:60]}{'…' if len(msg) > 60 else ''}[/]"
            for i, msg in enumerate(self._queued)
        ]
        return Panel(
            "\n".join(lines),
            title="Input Queue",
            border_style="blue",
            padding=(0, 1),
        )
```

#### 4.3 Modified REPL Loop

```python
def _async_repl(
    pt_session: PromptSession,
    session: Session,
    ...
) -> None:
    """REPL loop with async input support."""
    input_queue: queue.Queue[str] = queue.Queue()
    event_queue: queue.Queue[dict | None] = queue.Queue()
    preview = InputPreview()
    
    while True:
        # --- Phase: Prompt for user input ---
        raw = pt_session.prompt("You: ")
        # ... (handle commands, skip empty, etc.)
        
        # --- Phase: Start agent in background ---
        agent = AgentWorker(session, raw, input_queue, event_queue)
        agent.start()
        
        # --- Phase: Consume events + accept queued input ---
        while agent.is_alive() or not event_queue.empty():
            # Consume available events (non-blocking)
            try:
                event = event_queue.get_nowait()
                if event is None:  # sentinel
                    break
                render_event(event)
            except queue.Empty:
                pass
            
            # Check for user input (non-blocking)
            if _input_available():
                line = _read_line_nonblocking()
                if line:
                    input_queue.put(line)
                    preview.update(_drain_queue(input_queue))
                    _render_preview(preview)
            
            # Small sleep to avoid busy-waiting
            time.sleep(0.01)
        
        # --- Phase: Process queued input ---
        queued = _drain_queue(input_queue)
        if queued:
            for msg in queued:
                _console.print(f"\n[dim]Queued message:[/] {msg}")
                # Re-enter the loop with queued message
                # This is where we'd loop back
        else:
            preview.update([])
```

---

## 5. Phase 2: Steering Mid-Generation

### What the User Sees

```
Assistant: Let me read the file and analyze its structure…
           (tool call: read("session.py"))

User types (while model is executing): /steer also check the imports

The current tool result is preserved.
The model receives a new user message: "INTERRUPT: also check the imports"
  [Context: previous partial response and tool results are still in history]

Assistant: Good point. Let me also check what's imported in session.py…
```

### Key Design Decisions

**D1 — Steering vs Queueing**

| Mode | Trigger | Behavior |
|:---|---:|:---|
| **Queue** | User types normally while model streams | Input is buffered; sent as next turn when model finishes |
| **Steer** | User types `/steer <message>` or presses a hotkey | Current generation is interrupted; steering message is injected as next user input in the same turn |

**D2 — What Happens to Partial Output**

On steering:
1. Current stream is **cancelled** (same mechanism as Ctrl+C)
2. Partial assistant response is **preserved in history** (with a note: `INTERRUPTED_BY_STEERING`)
3. Steering message is appended to history as a **user message**
4. A new generation starts from the augmented history

This means the model sees: *"I was writing X, but the user said Y — continue from here."*

**D3 — Tool Execution Middle of Flight**

If a steering interrupt arrives while a tool is executing (particularly bash/edit/write), we have two options:

| Option | Pros | Cons |
|:---|---:|:---|
| **A — Wait for tool** | No partial tool results in history | Steering feels delayed |
| **B — Cancel tool** | Instant steering | Potentially dangerous (mid-write, mid-bash) |

**Recommendation: Option A — wait for current tool to finish, then steer.** Tools are fast (sub-second for read/write/edit). Bash can be long-running — for bash, we check the steering flag between commands and after each subprocess.

**D4 — Steer vs Ctrl+C**

| Action | Current | Proposed |
|:---|---:|:---|
| Ctrl+C (first press) | Cancel stream | **Show steering prompt**: `⏳ (Ctrl+C again to force) [steer]: ` |
| Ctrl+C (second press) | Hard exit | Hard exit (unchanged) |
| Type text during streaming | Lost | **Queued** (sent after model finishes) |
| `/steer <msg>` during streaming | Ignored | **Steers** (interrupts + injects) |

### Implementation

#### 5.1 `_SteeringInterrupt` Exception

```python
class _SteeringInterrupt(Exception):
    """Raised by the steer callback to interrupt the current generation."""
    def __init__(self, steer_message: str, partial_content: str):
        self.steer_message = steer_message
        self.partial_content = partial_content
```

#### 5.2 Modified `Session.chat()` with Steer Callback

```python
# In session.py

def chat(
    self,
    user_message: str,
    *,
    print_mode: bool = False,
    auto_confirm: bool = False,
    _steer_callback: Callable[[], str | None] | None = None,
) -> Generator[dict[str, Any]]:
    """Process a user message through the tool-calling loop.

    Parameters
    ----------
    _steer_callback : callable or None
        Called between SSE chunks and between tool rounds.
        Should return a steering message string, or None to continue.
        If a string is returned, a _SteeringInterrupt is raised
        to gracefully interrupt the current generation.
    """
    self.history.append({"role": "user", "content": user_message})
    messages = self.rebuild_messages("")
    messages = [m for m in messages if m.role != "user" or m.content]

    yield from self._handle_turn(
        messages,
        print_mode=print_mode,
        auto_confirm=auto_confirm,
        steer_callback=_steer_callback,
    )
```

#### 5.3 Modified `_handle_turn()` with Steer Support

```python
def _handle_turn(self, messages, *, steer_callback=None, ...):
    rounds = 0
    while rounds < self.max_tool_rounds:
        rounds += 1
        ...
        _mark_streaming_start()
        try:
            for delta in self.client.chat_stream(messages, tools=...):
                # Check for steering between SSE chunks
                if steer_callback:
                    steer_msg = steer_callback()
                    if steer_msg is not None:
                        cancelled = True
                        _steer_msg = steer_msg
                        break
                
                if is_cancel_requested():
                    cancelled = True
                    break
                ...
        finally:
            _mark_streaming_stop()

        if cancelled and _steer_msg:
            # Record partial response with steering marker
            if final_delta and final_delta.accumulated:
                partial = final_delta.accumulated
                self.history.append({
                    "role": "assistant",
                    "content": partial,
                    "steer_interrupted": True,
                })
            # Inject steering message as user input
            self.history.append({
                "role": "user",
                "content": f"INTERRUPT — {_steer_msg}",
            })
            # Rebuild and loop (yes, continue the same turn)
            yield {"type": "steer", "message": _steer_msg}
            messages = self.rebuild_messages("")
            messages = [m for m in messages if m.role != "user" or m.content]
            continue
        ...
```

#### 5.4 AgentWorker — The Threaded Wrapper

This is the **key new module** that connects the REPL thread to the agent thread:

```python
# cli/agent_worker.py

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

from mva.agent import Session


class AgentWorker:
    """Runs ``session.chat()`` on a background thread.

    Events are pushed to ``event_queue``.
    The REPL thread can put steering messages into ``steer_queue``.
    """

    STEER_POLL_INTERVAL = 0.05  # seconds between steer checks

    def __init__(self, session: Session):
        self._session = session
        self.event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.steer_queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, user_message: str) -> None:
        """Start processing a user message in the background."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(user_message,),
            daemon=True,
            name="agent-worker",
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the worker to stop at the next opportunity."""
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the worker thread to finish."""
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _steer_callback(self) -> str | None:
        """Called by Session between SSE chunks and tool rounds.

        Returns a steering message string, or None if no steer requested.
        """
        if self._stop_event.is_set():
            return "Cancelled."
        try:
            return self.steer_queue.get_nowait()
        except queue.Empty:
            return None

    def _run(self, user_message: str) -> None:
        """Worker thread entry point."""
        try:
            for event in self._session.chat(
                user_message,
                _steer_callback=self._steer_callback,
            ):
                if self._stop_event.is_set() and not self._is_terminal(event):
                    continue  # skip remaining events after stop
                self.event_queue.put(event)
                if event["type"] in ("done", "error"):
                    break
        except Exception as exc:
            self.event_queue.put({
                "type": "error",
                "content": f"Agent worker error: {exc}",
            })
        finally:
            self.event_queue.put(None)  # sentinel

    @staticmethod
    def _is_terminal(event: dict) -> bool:
        return event.get("type") in ("done", "error", "cancelled")
```

---

## 6. Phase 3: UI Enhancements (Split Pane, Input Preview)

### 6.1 `IncrementalInput` — prompt-toolkit-based async input reader

Uses prompt-toolkit's `Application` with a `Buffer` to accept input while the agent is running, without blocking the main event-processing loop.

```python
class QueuedInputReader:
    """Reads user input asynchronously using prompt-toolkit.

    Runs prompt-toolkit's ``Application`` in a background thread.
    Each complete line (Enter press) is put onto the output queue.
    """

    def __init__(self, output_queue: queue.Queue[str]):
        self._queue = output_queue
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the input reader thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """Read lines from stdin using prompt-toolkit."""
        from prompt_toolkit import PromptSession
        session = PromptSession(
            message="",
            vi_mode=False,
        )
        try:
            while True:
                line = session.prompt("⏎ ")
                self._queue.put(line)
        except (EOFError, KeyboardInterrupt):
            pass
```

**Simpler alternative for Phase 1:** Use `sys.stdin.readline()` with `select.poll()` for non-blocking reads:

```python
import select
import sys

def _input_available(timeout: float = 0.0) -> bool:
    """Check if stdin has data available to read."""
    if sys.stdin.isatty():
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return bool(r)
    return False

def _read_line_nonblocking() -> str | None:
    """Read a line from stdin if available, without blocking."""
    if not _input_available():
        return None
    try:
        return sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        return None
```

The `select` approach is **simpler** and has **zero new dependencies**, but loses rich input features (history, completion, editing) during streaming. The prompt-toolkit approach provides those but is more complex.

### 6.2 Split Terminal Layout

Using `rich.layout.Layout` to create a persistent three-pane layout:

```
┌──────────────────────────────────────────────────────────┐
│                    Output Pane                            │
│  (model output, tool calls, tool results)                 │
│                                                           │
│  scrolls as content is added                              │
└──────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│                  Input Queue Preview                      │
│  [Q1] also check session.py                              │
│  [Q2] /steer focus on error handling                     │
└──────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│ Prompt: ⚡ openai / gpt-4o  │  ↵ send msg  ↵↵ send cmd  │
│ You: _                                                    │
└──────────────────────────────────────────────────────────┘
```

This can be done with `rich.live.Live` + `Layout`, but introduces ANSI scrollback issues (see `renderer.py` notes). **Recommendation:** skip the persistent layout for now — just show the queue preview panel before the prompt line when items are queued.

### 6.3 Keyboard Controls During Streaming

| Key | Action | Phase |
|:---|---:|:---:|
| `Enter` | Submit current input line → queued or steered | P1 |
| `Ctrl+C` (1st) | Show **steer input line**: `⏳ (Ctrl+C again to force) [steer]: ` | P2 |
| `Ctrl+C` (2nd) | Hard exit (unchanged) | — |
| `Ctrl+Z` | Show queued input count in status line | P3 |
| `Escape` | Clear the current partial input line | P3 |

---

## 7. File-by-File Implementation Guide

### 7.1 New Files

| File | Purpose | Phases |
|:---|:---|---:|
| `src/mva/cli/agent_worker.py` | `AgentWorker` — threaded wrapper around `Session` | P1, P2 |
| `src/mva/cli/input_queue.py` | `InputQueue` — non-blocking stdin reader + queue display | P1 |
| `src/mva/cli/steering.py` | `SteeringInterrupt`, steer event types, steer handler | P2 |

### 7.2 Modified Files

#### `src/mva/agent/session.py`

**Changes:**
- Add `steer_callback: Callable[[], str | None] | None = None` parameter to `chat()` and `_handle_turn()`
- In the streaming loop (inside `_handle_turn`), call `steer_callback()` between SSE chunks
- When steer returns a message, set `cancelled = True` + record `_steer_msg`
- After cancellation path: detect steering, record partial output with marker, inject steering message as user input, and `continue` the tool loop
- New event type: `"steer"` — emitted when steering occurs
- New history entry marker: `"steer_interrupted": True` on the partial assistant message

```python
# session.py — key changes

def chat(
    self,
    user_message: str,
    *,
    print_mode: bool = False,
    auto_confirm: bool = False,
    _steer_callback: Callable[[], str | None] | None = None,
) -> Generator[dict[str, Any]]:
    ...
    yield from self._handle_turn(
        messages,
        print_mode=print_mode,
        auto_confirm=auto_confirm,
        steer_callback=_steer_callback,
    )

def _handle_turn(self, messages, *, steer_callback=None, ...):
    while rounds < self.max_tool_rounds:
        ...
        for delta in self.client.chat_stream(messages, tools=...):
            # --- Steering check between SSE chunks ---
            if steer_callback:
                steer_msg = steer_callback()
                if steer_msg is not None:
                    cancelled = True
                    _steer_msg = steer_msg
                    break
            
            if is_cancel_requested():
                cancelled = True
                break
            ...
        
        # --- After stream ends, handle steering ---
        if cancelled and _steer_msg:
            # Record partial assistant output (if any)
            if final_delta and final_delta.accumulated:
                self.history.append({
                    "role": "assistant",
                    "content": final_delta.accumulated,
                    "steer_interrupted": True,
                })
            # Emit steer event
            yield {"type": "steer", "message": _steer_msg}
            # Inject steering message as user input
            self.history.append({
                "role": "user",
                "content": _steer_msg,
            })
            # Rebuild messages and loop
            messages = self.rebuild_messages("")
            messages = [m for m in messages if m.role != "user" or m.content]
            continue
        
        ...  # normal cancel / tool / done handling
```

#### `src/mva/cli/repl.py`

**Changes:**
- New `_async_repl()` function (or parameter-flag on existing `_repl()`)
- Uses `AgentWorker` instead of calling `session.chat()` directly
- Main loop: consume events from `event_queue` + check stdin for queued input
- After agent finishes: process queued input (auto-send) or show prompt
- Ctrl+C during streaming shows steering prompt instead of immediate cancel

```python
# repl.py — simplified sketch of the async loop

def _async_repl(session, ...):
    worker = AgentWorker(session)
    input_queue: queue.Queue[str] = queue.Queue()
    
    while True:
        raw = pt_session.prompt("You: ")
        # ... command handling ...
        
        # Start agent
        worker.start(raw)
        
        # Event consumption loop
        steer_requested = None
        while worker.is_alive or not worker.event_queue.empty():
            try:
                event = worker.event_queue.get(timeout=0.05)
                if event is None:
                    break
                render_event(event)
                if event["type"] == "steer":
                    steer_requested = event["message"]
            except queue.Empty:
                pass
            
            # Check for user input during streaming
            if _input_available():
                line = _read_line_nonblocking()
                if line:
                    if line.startswith("/steer "):
                        worker.steer_queue.put(line[7:])
                    else:
                        input_queue.put(line)
        
        # After agent finishes
        queued = _drain_queue(input_queue)
        if steer_requested:
            # Steering was handled during the turn
            pass
        elif queued:
            for msg in queued:
                ...  # auto-send queued messages
```

#### `src/mva/cli/renderer.py`

**Changes:**
- Add support for new event type `"steer"` — renders as a blue panel: `🔄 Steered: <message>`
- Support `"steer_interrupted"` marker in `_render_done()` — dim note about interruption

```python
# In EventRenderer.render():
elif event_type == "steer":
    self._render_steer(event)

def _render_steer(self, event):
    _console.print(
        f"\n[bold blue]🔄 Steered: {event['message']}[/]"
    )
```

#### `src/mva/agent/_system.py`

**Changes:**
- Add `_steer_callback` propagation path in the signal handler area
- (Optionally) add a marker to the system prompt when steering has occurred

#### `src/mva/agent/types.py`

**Changes:**
- No changes needed (event types are plain dicts — `"steer"` is just a new string constant)

---

## 8. Timeline & Effort Summary

| Phase | Item | Files | Est. Time | Dependencies |
|:---:|---|---:|---:|:---|
| **P1** | **Input Queuing** | | **12–15h** | |
| P1.1 | `InputQueue` — non-blocking stdin reader | `cli/input_queue.py` | 3h | None |
| P1.2 | `AgentWorker` — threaded session wrapper | `cli/agent_worker.py` | 4h | P1.1 |
| P1.3 | Queue preview display | `cli/input_queue.py` (continued) | 2h | P1.1 |
| P1.4 | Modified REPL loop (pump events + check stdin) | `cli/repl.py` | 3h | P1.2 |
| P1.5 | Testing: queued input auto-send | — | 2h | P1.4 |
| **P2** | **Steering** | | **10–14h** | **P1** |
| P2.1 | `steer_callback` in `Session.chat()` + `_handle_turn()` | `agent/session.py` | 4h | P1.2 |
| P2.2 | `_SteeringInterrupt` + steer event type | `cli/steering.py` | 1h | P2.1 |
| P2.3 | Ctrl+C → steer prompt during streaming | `cli/repl.py` | 3h | P2.1 |
| P2.4 | Steering renderer (blue panel, interruption note) | `cli/renderer.py` | 1h | P2.2 |
| P2.5 | Testing: steer mid-tool-call, mid-stream | — | 3h | P2.3 |
| **P3** | **UI Polish** | | **8–12h** | **P2** |
| P3.1 | Queued input count in bottom toolbar | `cli/console.py` | 1h | P1 |
| P3.2 | `/queue` command (show/manage queued items) | `cli/_commands.py` | 2h | P1 |
| P3.3 | Keyboard shortcut for quick steer (`Alt+S`) | `cli/console.py` | 2h | P2 |
| P3.4 | Visual indicator during streaming ("⚡ Generating…") | `cli/renderer.py` | 1h | P1 |
| P3.5 | Edge-case: tool execution during steer | `agent/session.py`, `agent_worker.py` | 3h | P2 |
| **Total** | | | **30–41h** | |

### Recommended Ordering

| Week | Focus | Deliverables |
|:---:|:---|---|
| 1 | P1.1–P1.3 | `InputQueue` + `AgentWorker` + basic async REPL loop |
| 2 | P1.4–P1.5, P2.1–P2.2 | Working queued input + steering support in Session |
| 3 | P2.3–P2.5 | Steering UI (Ctrl+C prompt, steered rendering, testing) |
| 4 | P3.1–P3.5 | Polish (toolbar, commands, shortcuts, edge cases) |

---

## 9. Risk Register

### Technical Risks

| # | Risk | Likelihood | Impact | Mitigation |
|:---:|---|---|---:|:---|
| R1 | **Thread safety bugs** in `Session.history` | Medium | High — corrupted history, non-reproducible responses | Add `threading.Lock` around history mutations in `Session`; use `copy.deepcopy` when passing history to agent thread |
| R2 | **Race condition**: steer message processed after stream already ended | Low | Low — extra event, user sees no effect | Check `steer_callback()` return only during active streaming; ignore after `DONE` |
| R3 | **TTY corruption**: prompt-toolkit input conflicts with `sys.stdin` reads | High | High — garbled terminal | Use prompt-toolkit's built-in async API (`prompt_async()`) instead of raw stdin; if raw stdin must be used, save/restore TTY settings |
| R4 | **Resource leak**: zombie threads on Ctrl+C hard exit | Medium | Low — daemon threads are cleaned up on exit | Use `daemon=True` for all worker threads |
| R5 | **Tool execution during steer**: bash still running when steer requested | Medium | Medium — partial tool result in history | Wait for current tool to finish before steering; for long-running bash, inject a `SIGINT` into the subprocess group |

### UX Risks

| # | Risk | Likelihood | Mitigation |
|:---:|---|---:|
| R6 | User types a message mid-stream and forgets about it | Medium | Show queue preview prominently; drain/confirm on next prompt; add `/queue show` command |
| R7 | Steering feels slow when waiting for tool to finish | Medium | Show progress: `⏳ Waiting for tool to finish…` during the 1–3s window |
| R8 | Confusion: "did my message get queued or was it sent?" | Medium | Always show a confirmation: `[dim]📨 Queued: "message"[/]` or `[blue]🔄 Steered: "message"[/]` |

### Migration Risks

| # | Risk | Likelihood | Mitigation |
|:---:|---|---:|
| R9 | Existing plugin hooks (`on_pre_message`, `on_event`) need updating for new event flow | Medium | `PluginManager` already receives events — no change needed; async REPL just calls the same hooks |
| R10 | Single-run (`--print`) and non-interactive modes must not regress | Low | Keep `_run_single()` unchanged; async path is only in `_repl()` → renamed to `_async_repl()` |

---

## Appendix A: Event Type Reference (Updated)

### New Event Types

| Type | When | Payload |
|:---|---:|:---|
| `"steer"` | Steering message injected | `{"type": "steer", "message": str}` |

### Modified Event Types

| Type | Change |
|:---|:---|
| `"done"` | No change — content still contains full accumulated text |
| `"cancelled"` | No change — still emitted when user cancels without steering |
| `"delta"` | No change — still streamed token by token |

---

## Appendix B: History Structure (Updated)

### After Steering Interrupt

```json
[
    {"role": "user", "content": "Analyze the CLI architecture"},
    {"role": "assistant", "content": "Let me look at the files...",
     "tool_calls": [...], "steer_interrupted": true},
    {"role": "tool", "tool_call_id": "call_1",
     "content": "file contents..."},
    {"role": "user", "content": "Also check the error handling"},  ← steer injection
    {"role": "assistant", "content": "Good point. The error handling in..."}
]
```

The `steer_interrupted: true` marker tells the renderer to show a dim note about the interruption. The model sees the partial reasoning + tool results + the new steer message, enabling coherent continuation.

---

## Appendix C: Diagrams

### C1. Thread Interaction (Phase 1 — Input Queueing)

```
┌─────────────────────┐         ┌──────────────────────┐
│    REPL Thread       │         │    Agent Thread       │
│                      │         │                       │
│  prompt("You: ")     │         │                       │
│  user types message  │         │                       │
│  start_agent(msg) ───┼────────►│  session.chat(msg)   │
│                      │         │                       │
│  while agent alive:  │         │  for delta in stream: │
│   event=queue.get()──┼─────────┤   event_queue.put()   │
│   render(event)      │         │                       │
│                      │         │   if _input_check():  │
│  if stdin has data:  │         │     steer_queue.get() │
│   line = read()      │         │                       │
│   input_queue.put()  │         │                       │
│   show preview()     │◄────────┼── continue looping    │
│                      │         │                       │
│  agent done          │         │  event_queue.put(None)│
│  check input_queue ──┤         │  thread exits         │
│  if queued:          │         │                       │
│   auto-send next     │         │                       │
│  else:               │         │                       │
│   show prompt        │         │                       │
└─────────────────────┘         └──────────────────────┘
```

### C2. Event Flow with Steering (Phase 2)

```
REPL                         Agent                          Model
────                         ─────                          ─────
"read the code" ──────────►  session.chat() ──────────────►  streaming
                               │                              │
                               │ event_queue: delta           │◄──── chunks
render(delta) ◄───────────────┘                              │
                               │                                  
User types: "/steer also      │ steer_msg                        
check error handling" ──────► │  (from steer_callback())         
                               │                                  
                               │ partial output → history        
                               │ steer_msg → history (as user)   
                               │                                  
                               │ session.chat() ──────────────►  new stream
                               │ (from augmented history)        │
                               │ event_queue: delta              │◄──── chunks
render(delta) ◄───────────────┘                                 │
```

---

*Last updated: 2026-05-13*

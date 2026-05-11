"""Prompt-toolkit REPL session setup.

Provides the :class:`MVACompleter`, key bindings, toolbar factory, and
:func:`_create_prompt_session` used by the REPL loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style as PTStyle

from mva.agent import LLMClient, SkillDef

# ---------------------------------------------------------------------------
# History path
# ---------------------------------------------------------------------------

_HISTORY_DIR = Path.home() / ".config" / "mva"
_HISTORY_PATH = _HISTORY_DIR / "history"

# ---------------------------------------------------------------------------
# Module-level state (injected by the app at startup)
# ---------------------------------------------------------------------------

_client_ref: LLMClient | None = None
_skills_ref: list[SkillDef] | None = None


def set_client(client: LLMClient) -> None:
    """Store a reference to the active LLM client for the completer / toolbar."""
    global _client_ref  # noqa: PLW0603
    _client_ref = client


def set_skills(skills: list[SkillDef]) -> None:
    """Store the current skill list for the completer."""
    global _skills_ref  # noqa: PLW0603
    _skills_ref = skills


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

_PT_STYLE = PTStyle.from_dict(
    {
        "prompt": "bold green",
        "completion-menu.completion": "bg:#008888 #ffffff",
        "completion-menu.completion.current": "bg:#00aaaa #000000",
        "completion-menu.meta.completion": "bg:#004444 #ffffff",
        "completion-menu.meta.completion.current": "bg:#00aaaa #000000",
        "scrollbar.background": "bg:#88aaaa",
        "scrollbar.button": "bg:#222222",
        "bottom-toolbar": "bg:#222222 #888888",
    }
)


# ---------------------------------------------------------------------------
# Completer
# ---------------------------------------------------------------------------


class MVACompleter(Completer):
    """Dynamic tab completer for the MVA REPL.

    Provides completions for commands (``/exit``, ``/model``, ``/skill:``…),
    model names, provider names, and skill names.
    """

    COMMANDS = [
        "/exit",
        "/quit",
        "/clear",
        "/reset",
        "/help",
        "/history",
        "/model",
        "/provider",
        "/providers",
        "/tools",
        "/skills",
    ]

    def get_completions(
        self, document: Any, complete_event: Any
    ) -> list[Completion]:
        text = document.text_before_cursor

        # --- /skill:<name> completions ---
        if text.startswith("/skill:") and _skills_ref is not None:
            prefix = text[7:]
            for skill in _skills_ref:
                if skill.name.startswith(prefix):
                    yield Completion(
                        f"/skill:{skill.name}",
                        start_position=-len(text),
                        display=f"/skill:{skill.name}",
                        display_meta="toggle skill",
                    )
            return

        # --- /model <name> or /model <provider>/<model> completions ---
        if text.startswith("/model ") and _client_ref is not None:
            prefix = text[7:]

            # If prefix contains "/", we're in provider/model mode.
            # Complete model names within the specified provider.
            if "/" in prefix:
                prov_part, model_part = prefix.split("/", 1)
                prov_part = prov_part.strip()
                model_part = model_part.lstrip()
                try:
                    from mva.config import load_config  # noqa: PLC0415

                    cfg = load_config()
                    if prov_part in cfg.providers:
                        provider_cfg = cfg.providers[prov_part]
                        for model in (provider_cfg.models or []):
                            if model.startswith(model_part):
                                yield Completion(
                                    f"/model {prov_part}/{model}",
                                    start_position=-len(text),
                                    display=f"{prov_part}/{model}",
                                    display_meta="switch provider + model",
                                )
                except Exception:
                    pass
                return

            # No "/" yet — complete provider/model pairs first,
            # then plain model names.
            try:
                from mva.config import load_config  # noqa: PLC0415

                cfg = load_config()
                for prov_name, prov_cfg in cfg.providers.items():
                    if prov_name.startswith(prefix):
                        # Complete as provider prefix (for provider/model syntax)
                        yield Completion(
                            f"/model {prov_name}/",
                            start_position=-len(text),
                            display=f"{prov_name}/",
                            display_meta="switch provider + model",
                        )
                    # Complete full provider/model pairs
                    for model in (prov_cfg.models or []):
                        full = f"{prov_name}/{model}"
                        if full.startswith(prefix):
                            yield Completion(
                                f"/model {full}",
                                start_position=-len(text),
                                display=full,
                                display_meta="switch provider + model",
                            )
            except Exception:
                pass

            # Also complete plain model names from current provider
            for model in _client_ref.available_models:
                if model.startswith(prefix):
                    yield Completion(
                        f"/model {model}",
                        start_position=-len(text),
                        display=model,
                        display_meta="switch model",
                    )
            return

        # --- /provider <name> completions ---
        if text.startswith("/provider ") or text == "/provider":
            prefix = text[len("/provider "):] if text.startswith("/provider ") else ""
            try:
                from mva.config import load_config  # noqa: PLC0415

                cfg = load_config()
                for name in cfg.providers:
                    if name.startswith(prefix):
                        yield Completion(
                            f"/provider {name}",
                            start_position=-len(text),
                            display=name,
                            display_meta="switch provider",
                        )
            except Exception:
                pass
            return

        # --- /<command> completions ---
        if text.startswith("/"):
            for cmd in self.COMMANDS:
                if cmd.startswith(text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=cmd,
                        display_meta="command",
                    )
            return

        # No completions for regular text input


# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------


def _build_key_bindings() -> KeyBindings:
    """Create key bindings for the REPL prompt.

    - Ctrl+C / Ctrl+D: exit the prompt (returns empty string)
    - Tab: triggers completion
    """
    kb = KeyBindings()

    @kb.add("c-c")
    def _(event: Any) -> None:
        event.app.exit(result="")

    @kb.add("c-d")
    def _(event: Any) -> None:
        event.app.exit(result="")

    return kb


# ---------------------------------------------------------------------------
# Bottom toolbar
# ---------------------------------------------------------------------------


def _get_bottom_toolbar() -> str:
    """Return the current model/provider info for the bottom toolbar."""
    prov = _client_ref.current_provider if _client_ref else "?"
    model = _client_ref.default_model if _client_ref else ""
    ctx = f"⚡ {prov}"
    if model:
        ctx += f" / {model}"
    return ctx


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------


def _create_prompt_session() -> PromptSession:
    """Create and return a :class:`PromptSession` configured for MVA."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    return PromptSession(
        history=FileHistory(str(_HISTORY_PATH)),
        completer=MVACompleter(),
        auto_suggest=AutoSuggestFromHistory(),
        key_bindings=_build_key_bindings(),
        style=_PT_STYLE,
        bottom_toolbar=_get_bottom_toolbar,
        complete_while_typing=True,
        vi_mode=False,
        multiline=False,
    )

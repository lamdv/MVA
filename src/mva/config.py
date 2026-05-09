"""Configuration loader for MVA.

Loads model/provider configuration from ``model.yaml``, with fallback
to environment variables for backward compatibility.

Search order (first match wins):
    1. ``./.mva/model.yaml`` — project-level config
    2. ``~/.config/mva/model.yaml`` — user-level global config
    3. Environment variables (legacy fallback)

The ``model.yaml`` file supports multiple provider definitions, allowing
you to switch between different backends (OpenAI-compatible, Anthropic,
etc.) without editing environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""

    type: str = "openai"
    """Provider type. Currently supported: ``"openai"`` (OpenAI-compatible API)."""

    base_url: str = "http://127.0.0.1:8002/v1"
    """Base URL of the inference server (e.g. ``http://127.0.0.1:8002/v1``)."""

    api_key: str = "no-key"
    """API key. Use ``"no-key"`` for local servers."""

    default_model: str = ""
    """Default model identifier sent to the server."""

    models: list[str] = field(default_factory=list)
    """Available model identifiers for this provider.

    When non-empty, these are presented to the user and can be switched
    to at runtime with ``/model <name>``.  The first entry should match
    *default_model*.
    """

    timeout: int = 120
    """Request timeout in seconds."""


@dataclass
class ModelConfig:
    """Top-level configuration loaded from ``model.yaml``."""

    provider: str = "openai"
    """Key into the *providers* dict for the active provider."""

    providers: dict[str, ProviderConfig] = field(
        default_factory=lambda: {"openai": ProviderConfig()}
    )
    """Map of provider names to their configurations."""

    sandbox_dir: str = "./sandbox"
    """Directory for sandboxed file operations."""


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _find_config() -> Path | None:
    """Locate a ``model.yaml`` file.

    Checks (first match wins):
        1. ``.mva/model.yaml`` in the current working directory
        2. ``~/.config/mva/model.yaml`` in the user's global config directory

    Returns the path, or ``None`` if neither exists.
    """
    global _config_path

    # If we already loaded from a file, return that
    if _config_path is not None:
        return _config_path

    # Project-level (highest priority)
    project = Path.cwd() / ".mva" / "model.yaml"
    if project.is_file():
        _config_path = project
        return project

    # User-level global
    user = Path.home() / ".config" / "mva" / "model.yaml"
    if user.is_file():
        _config_path = user
        return user

    return None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(path: str | Path | None = None) -> ModelConfig:
    """Load configuration from a ``model.yaml`` file.

    Parameters
    ----------
    path:
        Explicit path to a ``model.yaml`` file.  When ``None`` (the
        default), auto-discover via :func:`_find_config`.

    Returns
    -------
    A :class:`ModelConfig` populated from the YAML file.  If no YAML
    file is found, falls back to environment variables (legacy) and
    then to hard-coded defaults.

    Raises
    ------
    ConfigError
        If the YAML file is invalid or missing required keys.
    """
    if path is None:
        path = _find_config()

    if path is not None:
        return _load_yaml(path)

    # Fallback: build from environment variables (legacy support)
    return _config_from_env()


def get_active_provider(config: ModelConfig | None = None) -> ProviderConfig:
    """Return the currently active provider configuration.

    Convenience helper that loads config if not provided, then looks up
    the active provider by key.
    """
    if config is None:
        config = load_config()
    prov = config.providers.get(config.provider)
    if prov is None:
        raise ConfigError(
            f"Active provider {config.provider!r} not found in providers. "
            f"Available: {list(config.providers)}"
        )
    return prov


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> ModelConfig:
    """Parse a ``model.yaml`` file and return a :class:`ModelConfig`."""
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        raise ConfigError(
            "PyYAML is required to parse model.yaml files. "
            "Install it with: uv add pyyaml"
        ) from None

    try:
        with open(path, encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc

    # Parse providers
    providers_raw = raw.get("providers", {})
    providers: dict[str, ProviderConfig] = {}
    for name, p in providers_raw.items():
        if not isinstance(p, dict):
            continue
        models_raw = p.get("models")
        if isinstance(models_raw, list):
            models = [str(m) for m in models_raw]
        else:
            models = []
        providers[name] = ProviderConfig(
            type=str(p.get("type", "openai")),
            base_url=str(p.get("base_url", "http://127.0.0.1:8002/v1")),
            api_key=str(p.get("api_key", "no-key")),
            default_model=str(p.get("default_model", "")),
            models=models,
            timeout=int(p.get("timeout", 120)),
        )

    # If no providers defined, seed with a default
    if not providers:
        providers["openai"] = ProviderConfig()

    return ModelConfig(
        provider=str(raw.get("provider", list(providers)[0])),
        providers=providers,
        sandbox_dir=str(raw.get("sandbox_dir", "./sandbox")),
    )


# ---------------------------------------------------------------------------
# Cache the loaded config path for runtime re-loading
# ---------------------------------------------------------------------------

_config_path: Path | None = None


def get_config_path() -> Path | None:
    """Return the path to the loaded config file, if any."""
    return _config_path


def reload_config(path: str | Path | None = None) -> ModelConfig:
    """Re-load configuration, optionally from an explicit path.

    This is useful for runtime provider switching: call ``load_config``
    fresh and update the :class:`LLMClient` accordingly.

    Parameters
    ----------
    path:
        Explicit path to a ``model.yaml`` file.  When ``None`` (the
        default), re-discover using the usual search order.

    Returns
    -------
    A fresh :class:`ModelConfig`.
    """
    global _config_path
    _config_path = None  # reset so _find_config re-searches
    return load_config(path)


def _config_from_env() -> ModelConfig:
    """Build a :class:`ModelConfig` from environment variables.

    Used as fallback when no ``model.yaml`` is found, ensuring backward
    compatibility with existing ``.env`` setups.
    """
    return ModelConfig(
        provider=os.environ.get("LLM_PROVIDER", "openai"),
        providers={
            "openai": ProviderConfig(
                type="openai",
                base_url=os.environ.get(
                    "LLM_BASE_URL", "http://127.0.0.1:8002/v1"
                ),
                api_key=os.environ.get("LLM_API_KEY", "no-key"),
                default_model=os.environ.get("DEFAULT_MODEL", ""),
                timeout=int(os.environ.get("LLM_TIMEOUT", "120")),
            ),
        },
        sandbox_dir=os.environ.get("SANDBOX_DIR", "./sandbox"),
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised when configuration loading fails."""

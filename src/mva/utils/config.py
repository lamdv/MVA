from pathlib import Path
from typing import Any

import yaml

# Search order: local first, then user-level
_CONFIG_PATHS = [
    Path("config.yml"),
    Path.home() / ".config" / "private-notebook" / "config.yml",
]


def load_config() -> dict[str, Any]:
    for path in _CONFIG_PATHS:
        if path.exists():
            with path.open() as f:
                return yaml.safe_load(f) or {}
    return {}

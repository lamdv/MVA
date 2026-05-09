"""``write`` tool — write content to files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mva.tools.base import SecurityCheck, Tool, ToolResult
from mva.tools.path_security import check_file_path_escape


class WriteTool(Tool):
    name = "write"
    description = (
        "Write content to a file. Creates the file if it doesn't exist, "
        "overwrites if it does. Automatically creates parent directories."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write (relative or absolute).",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file.",
            },
        },
        "required": ["path", "content"],
    }
    prompt_snippet = "Write content to a file"

    def check_security(self, path: str, **kwargs: Any) -> SecurityCheck | None:
        check = check_file_path_escape(path, str(Path.cwd()), operation="write")
        return None if check.safe else check

    def execute(
        self,
        path: str,
        content: str,
        _confirmed: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(
                content=f"Successfully wrote {len(content)} bytes to {path}"
            )
        except Exception as exc:
            return ToolResult(content=f"Error writing {path}: {exc}", is_error=True)

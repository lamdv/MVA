"""``list_files`` tool — directory listing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mva.tools.base import SecurityCheck, Tool, ToolResult
from mva.tools.path_security import check_file_path_escape


class ListFilesTool(Tool):
    name = "list_files"
    description = (
        "List files and directories in a given path. Supports recursive "
        "listing up to a specified depth (depth: recursion depth, "
        "starting from 1)."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Directory path to list (relative or absolute). "
                    "Defaults to current working directory."
                ),
            },
            "depth": {
                "type": "number",
                "description": "Recursion depth for listing (1 = top-level only). Defaults to 2.",
            },
            "limit": {
                "type": "number",
                "description": "Maximum number of entries to return. Defaults to 200.",
            },
        },
        "required": [],
    }
    prompt_snippet = "List files and directories"

    def check_security(self, path: str = ".", **kwargs: Any) -> SecurityCheck | None:
        check = check_file_path_escape(path, str(Path.cwd()), operation="list")
        return None if check.safe else check

    def execute(
        self,
        path: str = ".",
        depth: int = 2,
        limit: int = 200,
        _confirmed: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        p = Path(path)
        if not p.exists():
            return ToolResult(
                content=f"Error: Directory not found: {path}", is_error=True
            )
        if not p.is_dir():
            return ToolResult(
                content=f"Error: Not a directory: {path}", is_error=True
            )

        entries: list[str] = []
        depth = max(1, min(depth, 5))
        limit = max(1, min(limit, 1000))

        try:
            for current_depth in range(1, depth + 1):
                pattern = "*/" * (current_depth - 1) + "*"
                for item in sorted(p.glob(pattern)):
                    if len(entries) >= limit:
                        entries.append(f"... (truncated at {limit} entries)")
                        return ToolResult(content="\n".join(entries))
                    rel = item.relative_to(p)
                    prefix = "📁 " if item.is_dir() else "📄 "
                    entries.append(f"{prefix}{rel}")
        except Exception as exc:
            return ToolResult(content=f"Error listing {path}: {exc}", is_error=True)

        if not entries:
            return ToolResult(content=f"(empty directory: {p})")
        return ToolResult(content="\n".join(entries))

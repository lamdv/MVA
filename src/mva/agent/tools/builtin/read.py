"""``read`` tool — read text and image files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mva.agent.tools.base import SecurityCheck, Tool, ToolResult
from mva.agent.tools.path_security import check_file_path_escape


class ReadTool(Tool):
    name = "read"
    description = (
        "Read the contents of a file. Supports text files and images "
        "(jpg, png, gif, webp). For text files, output is truncated to "
        "2000 lines or 50KB (whichever is hit first). Use offset/limit "
        "for large files."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (relative or absolute).",
            },
            "offset": {
                "type": "number",
                "description": "Line number to start reading from (1-indexed).",
            },
            "limit": {
                "type": "number",
                "description": "Maximum number of lines to read.",
            },
        },
        "required": ["path"],
    }
    prompt_snippet = "Read file contents"

    def check_security(self, path: str, **kwargs: Any) -> SecurityCheck | None:
        check = check_file_path_escape(path, str(Path.cwd()), operation="read")
        return None if check.safe else check

    def execute(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
        _confirmed: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        p = Path(path)
        if not p.exists():
            return ToolResult(content=f"Error: File not found: {path}", is_error=True)
        if not p.is_file():
            return ToolResult(content=f"Error: Not a file: {path}", is_error=True)

        # Image detection
        suffix = p.suffix.lower()
        if suffix in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            return ToolResult(content=f"(image at {path})")

        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as exc:
            return ToolResult(content=f"Error reading {path}: {exc}", is_error=True)

        total = len(lines)
        start = max(0, offset - 1)
        if limit is not None:
            end = min(total, start + limit)
        else:
            end = min(total, start + 2000)

        result_lines = lines[start:end]
        content = "".join(result_lines)

        # 50KB cap
        max_bytes = 50 * 1024
        encoded = content.encode("utf-8")
        if len(encoded) > max_bytes:
            truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
            truncated += f"\n\n[Truncated at {max_bytes // 1024}KB]"
            return ToolResult(content=truncated)

        if end < total:
            content += f"\n\n[Lines {start+1}-{end} of {total}]"
        return ToolResult(content=content)

"""``edit`` tool — search-and-replace file editing for the LLM.

The LLM provides an exact block of text to find (``search_block``) and
the replacement text (``replace_block``).  The tool:

* Reads the file.
* Finds **exactly one** occurrence of ``search_block``.
* Replaces it with ``replace_block``.
* Writes the result and returns a unified diff.

If the search block is **not found**, the tool returns a helpful error
with the closest matching lines so the model can adjust its search.
If the search block appears **multiple times**, the tool reports all
occurrence line numbers so the model can make the search block more
specific.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any

from mva.tools.base import SecurityCheck, Tool, ToolResult
from mva.tools.path_security import check_file_path_escape

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_DIFF_LINES = 80


def _unified_diff(
    original: str,
    modified: str,
    filepath: str,
    *,
    context_lines: int = 3,
) -> str:
    """Generate a compact unified diff of *original* -> *modified*."""
    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_lines,
        mod_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
        n=context_lines,
    )
    lines = list(diff)
    if len(lines) > _MAX_DIFF_LINES:
        lines = lines[:_MAX_DIFF_LINES] + [
            f"... (diff truncated at {_MAX_DIFF_LINES} lines)\n"
        ]
    return "".join(lines)


def _find_closest_lines(
    content: str,
    search_block: str,
    max_candidates: int = 3,
) -> list[str]:
    """Find lines in *content* that are closest to *search_block*.

    Used to produce helpful error messages when the exact match fails.
    Returns a short list of contextual snippets.
    """
    search_lines = search_block.strip().splitlines()
    if not search_lines:
        return []

    # Use the first line of the search block as a probe
    probe = search_lines[0].strip()
    content_lines = content.splitlines()

    candidates: list[str] = []
    for i, line in enumerate(content_lines):
        if probe in line:
            start = max(0, i - 1)
            end = min(len(content_lines), i + 2)
            snippet = "\n".join(
                f"{j+1}:{content_lines[j]}"
                for j in range(start, end)
            )
            if snippet not in candidates:
                candidates.append(snippet)
            if len(candidates) >= max_candidates:
                break

    return candidates


def _is_text_file(path: Path) -> bool:
    """Quick check whether *path* looks like a text file."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return not bool(chunk) or b"\x00" not in chunk
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class EditTool(Tool):
    """Search-and-replace file editor.

    The LLM provides the exact block of text to find and its replacement.
    This avoids the brittleness of line-number-based editing (which breaks
    when files change between tool calls) while staying fully deterministic.
    """

    name = "edit"
    description = (
        "Edit a file by searching for an exact block of text and replacing "
        "it with new content. This is the preferred way to make targeted "
        "changes to existing files. The search_block must **exactly match** "
        "the existing content, including whitespace and indentation. "
        "If the search_block is found multiple times, the tool reports all "
        "occurrence locations so you can make the search block more specific. "
        "If the search_block is not found, the tool returns the closest "
        "matching lines to help you adjust.\n\n"
        "Use cases:\n"
        "- **Replace code**: search for the old code block, provide the new one.\n"
        "- **Insert code**: search for an insertion point (e.g. a closing brace "
        "or a function body line) and replace it with itself plus the new code.\n"
        "- **Delete code**: search for the code to remove and set replace_block to "
        "an empty string.\n\n"
        "Tip: include surrounding context (2-3 lines above and below) in the "
        "search_block to make the match unique."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit (relative or absolute).",
            },
            "search_block": {
                "type": "string",
                "description": (
                    "Exact text block to find and replace. Must match the "
                    "existing content exactly, including all whitespace, "
                    "indentation, and surrounding context. Include enough "
                    "context (2-3 lines above and below the target) to make "
                    "the match unique."
                ),
            },
            "replace_block": {
                "type": "string",
                "description": (
                    "New text block to replace the search_block with. "
                    "Can be empty (to delete code) or contain multiple lines."
                ),
            },
        },
        "required": ["path", "search_block", "replace_block"],
    }
    prompt_snippet = "Edit a file (search-and-replace)"

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------

    def check_security(self, path: str, **kwargs: Any) -> SecurityCheck | None:
        check = check_file_path_escape(path, str(Path.cwd()), operation="edit")
        return None if check.safe else check

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(
        self,
        path: str,
        search_block: str,
        replace_block: str,
        _confirmed: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        # -- Validate inputs -----------------------------------------------
        if not search_block:
            return ToolResult(
                content="Error: search_block cannot be empty.",
                is_error=True,
            )

        p = Path(path)
        if not p.exists():
            return ToolResult(
                content=f"Error: File not found: {path}",
                is_error=True,
            )
        if not p.is_file():
            return ToolResult(
                content=f"Error: Not a file: {path}",
                is_error=True,
            )

        if not _is_text_file(p):
            return ToolResult(
                content=f"Error: Not a text file (or contains binary data): {path}",
                is_error=True,
            )

        # -- Read the file --------------------------------------------------
        try:
            original_content = p.read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult(
                content=f"Error reading {path}: {exc}",
                is_error=True,
            )

        # -- Count occurrences ----------------------------------------------
        count = original_content.count(search_block)

        if count == 0:
            return self._handle_not_found(original_content, search_block, path)

        if count > 1:
            return self._handle_multiple_matches(
                original_content, search_block, count, path
            )

        # -- Exactly one match — perform the edit --------------------------
        modified_content = original_content.replace(search_block, replace_block, 1)

        # Generate diff before writing
        diff = _unified_diff(original_content, modified_content, path)

        # -- Write the file --------------------------------------------------
        try:
            p.write_text(modified_content, encoding="utf-8")
        except Exception as exc:
            return ToolResult(
                content=f"Error writing {path}: {exc}",
                is_error=True,
            )

        # -- Build success response -----------------------------------------
        orig_lines = original_content.count("\n")
        mod_lines = modified_content.count("\n")
        line_delta = mod_lines - orig_lines
        delta_sign = "+" if line_delta >= 0 else ""
        size = len(modified_content)

        summary_parts = [
            f"Successfully edited {path} ({size} bytes, "
            f"{orig_lines} → {mod_lines} lines, "
            f"{delta_sign}{line_delta} lines)."
        ]

        if diff:
            summary_parts.append("\nDiff:\n" + diff)

        return ToolResult(content="\n".join(summary_parts))

    # ------------------------------------------------------------------
    # Error helpers
    # ------------------------------------------------------------------

    def _handle_not_found(
        self,
        content: str,
        search_block: str,
        path: str,
    ) -> ToolResult:
        """Build a helpful error when the search block isn't found."""
        candidates = _find_closest_lines(content, search_block)

        msg_parts = [
            f"Error: search_block not found in {path}.",
            "",
            "Make sure the search_block **exactly** matches the file content "
            "(including whitespace, indentation, and surrounding context).",
        ]

        if candidates:
            msg_parts.extend([
                "",
                "Closest matching lines in the file:",
                "```",
                *candidates,
                "```",
                "",
                "Tip: include 2-3 lines of surrounding context above and "
                "below the target code to ensure a unique match.",
            ])

        # Check for whitespace mismatch
        stripped_search = search_block.strip()
        stripped_content = content.strip()
        if stripped_search in stripped_content:
            msg_parts.extend([
                "",
                "Note: The search_block text was found after stripping "
                "whitespace. Check indentation or trailing whitespace.",
            ])

        return ToolResult(content="\n".join(msg_parts), is_error=True)

    def _handle_multiple_matches(
        self,
        content: str,
        search_block: str,
        count: int,
        path: str,
    ) -> ToolResult:
        """Build a helpful error when the search block matches multiple times."""
        # Find all occurrence line numbers
        occurrences: list[int] = []
        start = 0
        while True:
            idx = content.find(search_block, start)
            if idx == -1:
                break
            line_no = content[:idx].count("\n") + 1
            occurrences.append(line_no)
            start = idx + 1

        lines_str = ", ".join(f"line {ln}" for ln in occurrences)

        msg_parts = [
            f"Error: search_block found {count} times in {path} at "
            f"{lines_str}.",
            "",
            "Make the search_block more specific by including more "
            "surrounding context (2-3 lines above and below the target).",
        ]

        return ToolResult(content="\n".join(msg_parts), is_error=True)

from mva.agent.tools import sandbox
from pathlib import Path
from typing import Tuple

@sandbox(params=["file_path", "search_text", "replacement_text", "occurrences"])
def replace_text(
    file_path: str,
    search_text: str,
    replacement_text: str,
    occurrences: int = -1
) -> str:
    """
    Replace part of the text in a file without overwriting the entire file.

    This tool searches for a substring (search_text) in the specified file and
    replaces it with replacement_text. You can control how many occurrences to
    replace using the occurrences parameter. By default, all occurrences are
    replaced. The original file is backed up before modification.

    Args:
        file_path: String path to the file to modify.
        search_text: The substring to search for. Must be non-empty.
        replacement_text: The string to replace search_text with.
        occurrences: Number of occurrences to replace. -1 (default) replaces all.
                     Use a positive integer to limit replacements (e.g., 1 for first only).

    Returns:
        A descriptive message indicating success, including:
        - Number of replacements made
        - File path modified
        - Original and replacement text preview

    Raises:
        FileNotFoundError: If the specified file does not exist.
        ValueError: If search_text is empty or occurrences is invalid.
        PermissionError: If write access to the file is denied.
        IOError: If there is a general file system error.

    Examples:
        >>> result = replace_text("./config.py", "DEBUG=False", "DEBUG=True")
        >>> print(result)
        'Successfully replaced 1 occurrence(s) in ./config.py'

        >>> result = replace_text("./data.txt", "old_value", "new_value", occurrences=2)
        >>> print(result)
        'Successfully replaced 2 occurrence(s) in ./data.txt'
    """
    # Step 1: Convert to Path object
    path = Path(file_path)

    # Step 2: Validate parameters
    if not search_text:
        raise ValueError("search_text cannot be empty")
    if occurrences == 0 or (occurrences < -1):
        raise ValueError("occurrences must be -1 (all) or a positive integer")

    # Step 3: Validation checks
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    try:
        # Step 4: Read original content
        original_content = path.read_text(encoding="utf-8")

        # Step 5: Check if search text exists
        if search_text not in original_content:
            raise ValueError(
                f"Search text not found in file: {path}\n"
                f"Searching for: {search_text[:100]}"
            )

        # Step 6: Perform replacement
        if occurrences == -1:
            # Replace all occurrences
            new_content = original_content.replace(search_text, replacement_text)
            count = original_content.count(search_text)
        else:
            # Replace specific number of occurrences
            new_content = original_content.replace(
                search_text, replacement_text, occurrences
            )
            count = occurrences

        # Step 7: Create backup before writing
        backup_path = path.with_stem(f"{path.stem}.backup")
        backup_path.write_text(original_content, encoding="utf-8")

        # Step 8: Write modified content back to file
        path.write_text(new_content, encoding="utf-8")

        # Step 9: Return success message
        search_preview = search_text[:50] + "..." if len(search_text) > 50 else search_text
        replacement_preview = (
            replacement_text[:50] + "..." if len(replacement_text) > 50 else replacement_text
        )

        return (
            f"Successfully replaced {count} occurrence(s) in {path}\n"
            f"Backup saved to: {backup_path}\n"
            f"Replaced: '{search_preview}' → '{replacement_preview}'"
        )

    except PermissionError as e:
        raise PermissionError(f"Permission denied modifying {path}: {e}")
    except IOError as e:
        raise IOError(f"I/O error modifying {path}: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during text replacement: {e}")


# Example Usage
if __name__ == "__main__":
    # Example 1: Replace all occurrences
    try:
        result = replace_text(
            "./example.txt",
            "old_value",
            "new_value"
        )
        print(result)
    except Exception as e:
        print(f"Error: {e}")

    # Example 2: Replace only first occurrence
    try:
        result = replace_text(
            "./example.txt",
            "duplicate",
            "unique",
            occurrences=1
        )
        print(result)
    except Exception as e:
        print(f"Error: {e}")

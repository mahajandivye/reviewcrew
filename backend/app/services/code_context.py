"""Turn a stored diff back into reviewable source.

Used by metrics, test generation and chat context: all three need the code a
review looked at, not just the findings. For pasted input every line is an
addition, so the original file can be reconstructed exactly.
"""

from __future__ import annotations

from app.services.diff_parser import added_lines_by_file, parse_unified_diff


def added_code_by_file(diff_text: str) -> dict[str, str]:
    """{path: source} built from the diff's added lines, in line order."""
    if not diff_text.strip():
        return {}
    files = parse_unified_diff(diff_text)
    added = added_lines_by_file(files)
    return {
        path: "\n".join(lines[number] for number in sorted(lines))
        for path, lines in added.items()
    }


def primary_code(diff_text: str) -> str:
    """The whole reviewed blob, with file headers when there are several files."""
    code_by_file = added_code_by_file(diff_text)
    if not code_by_file:
        return ""
    if len(code_by_file) == 1:
        return next(iter(code_by_file.values()))
    return "\n\n".join(
        f"# === {path} ===\n{code}" for path, code in sorted(code_by_file.items())
    )

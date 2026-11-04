"""Unified diff parsing.

WHY THIS EXISTS
---------------
GitHub reports a PR as "changed files", each with a *patch* that looks like:

    @@ -10,6 +10,8 @@ def handler(request):
         user = get_user(request)      <- context line (exists in both versions)
    -    return user.name              <- removed line
    +    if user is None:              <- added line
    +        return "anonymous"
    +    return user.name

The `@@ -old_start,old_count +new_start,new_count @@` header is the Rosetta
stone: it tells us which line numbers the following lines correspond to.

We need two things from it:
  1. Which NEW-file lines can carry an inline GitHub comment. GitHub rejects
     (HTTP 422) a comment on a line that is not part of the diff. Context and
     added lines are commentable; removed lines are not.
  2. The exact text of added lines, so the secret scanner can report a real
     line number instead of "somewhere in this file".

`parse_unified_diff` is also what feeds the Phase 4 split diff viewer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<section>.*)$"
)

# "diff --git a/old/path b/new/path" - used for binary files, which have no
# ---/+++ header lines.
_GIT_HEADER_RE = re.compile(r"^diff --git a/(?P<old>.+) b/(?P<new>.+)$")

# Extensions we can label in the UI. Not used for analysis decisions.
_LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".json": "JSON",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".css": "CSS",
    ".html": "HTML",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cpp": "C++",
    ".env": "Dotenv",
}


@dataclass(slots=True)
class DiffLine:
    """One line of a hunk, with its position in both file versions."""

    kind: str  # "add" | "del" | "context"
    old_line: int | None
    new_line: int | None
    content: str  # WITHOUT the leading +/-/space


@dataclass(slots=True)
class DiffHunk:
    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section: str = ""
    lines: list[DiffLine] = field(default_factory=list)


@dataclass(slots=True)
class FileDiff:
    path: str  # new path (or old path for deleted files)
    old_path: str | None = None
    new_path: str | None = None
    status: str = "modified"  # added | removed | modified | renamed
    hunks: list[DiffHunk] = field(default_factory=list)
    is_binary: bool = False

    # -- convenience ---------------------------------------------------- #
    @property
    def language(self) -> str:
        for suffix, name in _LANGUAGES.items():
            if self.path.lower().endswith(suffix):
                return name
        return "Plain text"

    @property
    def added_lines(self) -> dict[int, str]:
        """{new_line_number: text} for every line this PR added."""
        out: dict[int, str] = {}
        for hunk in self.hunks:
            for line in hunk.lines:
                if line.kind == "add" and line.new_line is not None:
                    out[line.new_line] = line.content
        return out

    @property
    def removed_lines(self) -> dict[int, str]:
        out: dict[int, str] = {}
        for hunk in self.hunks:
            for line in hunk.lines:
                if line.kind == "del" and line.old_line is not None:
                    out[line.old_line] = line.content
        return out

    @property
    def commentable_lines(self) -> set[int]:
        """New-file lines GitHub will accept an inline comment on."""
        lines: set[int] = set()
        for hunk in self.hunks:
            for line in hunk.lines:
                if line.new_line is not None:
                    lines.add(line.new_line)
        return lines

    def stats(self) -> tuple[int, int]:
        """(additions, deletions) for this file."""
        return len(self.added_lines), len(self.removed_lines)


def _clean_path(raw: str) -> str | None:
    """`a/backend/app/main.py` -> `backend/app/main.py`; `/dev/null` -> None."""
    raw = raw.strip()
    if not raw:
        return None
    # Paths containing spaces are quoted by git: "a/dir with space/file.py"
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        raw = raw[1:-1]
    if raw == "/dev/null":
        return None
    if raw.startswith(("a/", "b/")):
        return raw[2:]
    return raw


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """Parse a git-style unified diff into FileDiff objects.

    Tolerant by design: unknown lines are ignored rather than raising, because
    real-world diffs contain `index`, mode changes, binary markers, etc.
    """
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: DiffHunk | None = None
    old_no = new_no = 0

    for raw in diff_text.splitlines():
        # --- new file block -------------------------------------------- #
        if raw.startswith("diff --git "):
            current = FileDiff(path="")
            files.append(current)
            hunk = None
            # Parse "diff --git a/x b/y" as a fallback. Binary files have no
            # ---/+++ lines, so without this they would end up with no path.
            header = _GIT_HEADER_RE.match(raw)
            if header:
                current.old_path = _clean_path(header.group("old"))
                current.new_path = _clean_path(header.group("new"))
                current.path = current.new_path or current.old_path or ""
            continue

        if raw.startswith("--- "):
            if current is None:  # patch without a `diff --git` header
                current = FileDiff(path="")
                files.append(current)
            current.old_path = _clean_path(raw[4:])
            if current.old_path is None and current.status == "modified":
                current.status = "added"
            continue

        if raw.startswith("+++ "):
            if current is None:
                current = FileDiff(path="")
                files.append(current)
            current.new_path = _clean_path(raw[4:])
            if current.new_path is None:
                current.status = "removed"
            continue

        if raw.startswith("@@ "):
            match = HUNK_RE.match(raw)
            if not match or current is None:
                continue
            hunk = DiffHunk(
                header=raw,
                old_start=int(match.group("old_start")),
                old_count=int(match.group("old_count") or 1),
                new_start=int(match.group("new_start")),
                new_count=int(match.group("new_count") or 1),
                section=match.group("section").strip(),
            )
            current.hunks.append(hunk)
            old_no = hunk.old_start
            new_no = hunk.new_start
            continue

        # --- hunk body -------------------------------------------------- #
        if hunk is None or current is None:
            # Headers we do not care about: index, mode, rename, similarity...
            if current is None:
                continue
            if raw.startswith("new file mode"):
                current.status = "added"
            elif raw.startswith("deleted file mode"):
                current.status = "removed"
            elif raw.startswith(("rename from", "rename to")):
                current.status = "renamed"
            elif raw.startswith(("Binary files", "GIT binary patch")):
                current.is_binary = True
            continue

        if raw.startswith("\\"):  # "\ No newline at end of file"
            continue

        prefix, content = raw[:1], raw[1:]
        if prefix == "+":
            hunk.lines.append(DiffLine("add", None, new_no, content))
            new_no += 1
        elif prefix == "-":
            hunk.lines.append(DiffLine("del", old_no, None, content))
            old_no += 1
        elif prefix == " ":
            hunk.lines.append(DiffLine("context", old_no, new_no, content))
            old_no += 1
            new_no += 1
        # Anything else (e.g. "" empty line inside a weird patch) is skipped.

    # --- fill in display paths ----------------------------------------- #
    for f in files:
        f.path = f.new_path or f.old_path or ""
        if f.status == "modified" and f.old_path and f.new_path and f.old_path != f.new_path:
            f.status = "renamed"

    return [f for f in files if f.path]


def build_diff_text(
    files: list[dict[str, str | None]],
) -> str:
    """Synthesise a parseable unified diff from GitHub's per-file patches.

    The GitHub API gives us each file's `patch` (hunk only, no `diff --git`
    header). Adding minimal headers here means ONE parser handles everything,
    and the stored `diff_text` is a normal git diff you can read yourself.

    Each entry accepts: path, old_path, patch and optional status
    ("added" | "removed" | "modified" | "renamed"). Status matters because
    GitHub omits the patch for binaries and the UI wants a correct badge.
    """
    parts: list[str] = []
    for entry in files:
        path = str(entry.get("path") or "")
        patch = entry.get("patch")
        old_path = str(entry.get("old_path") or path)
        status = str(entry.get("status") or "modified")
        if not path:
            continue
        parts.append(f"diff --git a/{old_path} b/{path}")
        if status == "added":
            parts.append("new file mode 100644")
        elif status == "removed":
            parts.append("deleted file mode 100644")
        if not patch:
            # Binary file or patch omitted by GitHub (too large).
            parts.append(f"Binary files a/{old_path} and b/{path} differ")
            continue
        parts.append(f"--- {'/dev/null' if status == 'added' else f'a/{old_path}'}")
        parts.append(f"+++ {'/dev/null' if status == 'removed' else f'b/{path}'}")
        parts.append(str(patch).rstrip("\n"))
    return "\n".join(parts) + "\n" if parts else ""


def added_lines_by_file(files: list[FileDiff]) -> dict[str, dict[int, str]]:
    """{path: {line_no: text}} for all added lines, skipping binaries."""
    return {f.path: f.added_lines for f in files if f.added_lines and not f.is_binary}


def commentable_lines_by_file(files: list[FileDiff]) -> dict[str, set[int]]:
    """{path: {line numbers}} that can host inline GitHub comments."""
    return {f.path: f.commentable_lines for f in files if f.commentable_lines}


def is_python(path: str) -> bool:
    return path.lower().endswith(".py")

"""A source-agnostic finding representation + helpers.

All three engines (AI, pyflakes, secret scanner) produce `FindingDraft`s.
Keeping them in one shape means the persistence layer and the GitHub comment
poster never need to care where a finding came from.

This module deliberately has NO imports from `app.database` / `app.models`,
so it can be unit-tested without a database.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import SEVERITY_RANK, Category, FindingSource, Severity

MAX_MESSAGE_CHARS = 2_000
MAX_SUGGESTION_CHARS = 4_000
MAX_EVIDENCE_CHARS = 1_000


@dataclass(slots=True)
class FindingDraft:
    """A finding that has not been saved yet."""

    file_path: str
    line_number: int
    severity: str
    category: str
    message: str
    suggestion: str | None = None
    source: str = FindingSource.AI.value
    evidence: str | None = None
    confidence: float = 0.65

    def normalised(self) -> "FindingDraft":
        """Clamp/clean LLM output before it reaches the database.

        Models occasionally return `"line": "42"`, a line of 0, a 5000-char
        paragraph, or severity "critical" instead of "high". Everything is
        normalised here, once, instead of in three different places.
        """
        severity = str(self.severity or "").strip().lower()
        if severity not in {s.value for s in Severity}:
            severity = (
                Severity.HIGH.value
                if severity in {"critical", "blocker", "error"}
                else Severity.LOW.value
                if severity in {"info", "nit", "trivial"}
                else Severity.MEDIUM.value
            )

        category = str(self.category or "").strip().lower()
        if category not in {c.value for c in Category}:
            category = Category.BUG.value

        try:
            line = int(self.line_number)
        except (TypeError, ValueError):
            line = 1
        line = max(1, line)

        message = (self.message or "").strip()[:MAX_MESSAGE_CHARS] or "No description provided."
        suggestion = (self.suggestion or "").strip()[:MAX_SUGGESTION_CHARS] or None
        evidence = (self.evidence or "").strip()[:MAX_EVIDENCE_CHARS] or None
        try:
            confidence = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            confidence = 0.65

        return FindingDraft(
            file_path=str(self.file_path or "").strip().lstrip("/"),
            line_number=line,
            severity=severity,
            category=category,
            message=message,
            suggestion=suggestion,
            source=self.source,
            evidence=evidence,
            confidence=confidence,
        )


def finding_fingerprint(file_path: str, line_number: int, message: str) -> str:
    """Identity used for de-duplication (same file + line + message)."""
    return f"{file_path.strip().lower()}::{line_number}::{message.strip().lower()}"


def dedupe_findings(drafts: list[FindingDraft]) -> list[FindingDraft]:
    """Keep one finding per (file, line, message).

    The three engines overlap: pyflakes says "undefined name 'x'", and the AI
    often reports the same undefined name on the same line with different
    wording. Exact-response duplicates are also common when the model repeats
    an item. Posting both looks sloppy on a PR, so the first one wins.
    """
    seen: set[str] = set()
    unique: list[FindingDraft] = []
    for draft in drafts:
        key = finding_fingerprint(draft.file_path, draft.line_number, draft.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(draft)
    return unique


def rank_findings(drafts: list[FindingDraft]) -> list[FindingDraft]:
    """Sort high -> medium -> low, then by file and line.

    Ordering matters twice: the first 10 findings are what a reviewer actually
    reads, and the PR summary lists them in this order.
    """
    return sorted(
        drafts,
        key=lambda draft: (
            SEVERITY_RANK.get(draft.severity, 99),
            draft.file_path,
            draft.line_number,
        ),
    )

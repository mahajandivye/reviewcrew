"""Tests for de-duplication and severity ranking of findings."""

from __future__ import annotations

from app.services.findings import (
    FindingDraft,
    dedupe_findings,
    finding_fingerprint,
    rank_findings,
)


def draft(path, line, severity, message, source="ai"):
    return FindingDraft(
        file_path=path,
        line_number=line,
        severity=severity,
        category="bug",
        message=message,
        source=source,
    )


def test_same_file_line_message_is_deduped():
    drafts = [
        draft("app/main.py", 10, "high", "undefined name 'x'", source="static"),
        draft("app/main.py", 10, "high", "undefined name 'x'", source="ai"),
    ]
    assert len(dedupe_findings(drafts)) == 1


def test_dedupe_is_case_and_whitespace_insensitive():
    drafts = [
        draft("app/main.py", 10, "high", "Undefined Name 'x'"),
        draft("app/main.py", 10, "high", "  undefined name 'x'  "),
    ]
    assert len(dedupe_findings(drafts)) == 1


def test_different_lines_are_kept():
    drafts = [
        draft("app/main.py", 10, "high", "same message"),
        draft("app/main.py", 11, "high", "same message"),
    ]
    assert len(dedupe_findings(drafts)) == 2


def test_different_files_are_kept():
    drafts = [
        draft("app/a.py", 10, "high", "same message"),
        draft("app/b.py", 10, "high", "same message"),
    ]
    assert len(dedupe_findings(drafts)) == 2


def test_ranking_is_high_then_medium_then_low():
    drafts = [
        draft("z.py", 1, "low", "l"),
        draft("a.py", 9, "high", "h2"),
        draft("a.py", 2, "medium", "m"),
        draft("a.py", 3, "high", "h1"),
    ]
    ranked = rank_findings(drafts)
    assert [d.severity for d in ranked] == ["high", "high", "medium", "low"]
    # Within the same severity, order is by file then line.
    assert [d.message for d in ranked][:2] == ["h1", "h2"]


def test_fingerprint_normalises_case():
    assert finding_fingerprint("A.py", 1, "Boom") == finding_fingerprint("a.py", 1, "boom")

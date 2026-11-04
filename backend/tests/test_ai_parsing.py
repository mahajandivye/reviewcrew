"""Unit tests for the AI response parser.

The OpenAI call itself is not tested here (it would need a key and network);
what IS tested is the part that breaks in production: turning messy model
output into valid findings.
"""

from __future__ import annotations

import pytest

from app.services.ai_reviewer import (
    AIReviewError,
    AIReviewer,
    SYSTEM_PROMPT,
    parse_ai_findings,
)

ALLOWED = {"app/main.py", "app/services/checkout.py"}


def test_system_prompt_formats_without_key_error():
    # The prompt contains literal JSON braces, which must be escaped for
    # str.format(). A KeyError here would break every review at runtime.
    rendered = SYSTEM_PROMPT.format(max_findings=10)
    assert '"findings"' in rendered
    assert "10 findings" in rendered


def test_parses_the_documented_schema():
    raw = """
    {
      "findings": [
        {
          "file": "app/main.py",
          "line": 42,
          "severity": "high",
          "category": "bug",
          "message": "Off-by-one in the pagination loop.",
          "suggestion": "Use `range(0, n)`."
        }
      ]
    }
    """
    drafts = parse_ai_findings(raw, allowed_files=ALLOWED)
    assert len(drafts) == 1
    assert drafts[0].file_path == "app/main.py"
    assert drafts[0].line_number == 42
    assert drafts[0].severity == "high"
    assert drafts[0].source == "ai"


def test_strips_markdown_code_fences():
    raw = '```json\n{"findings": [{"file": "app/main.py", "line": 1, "severity": "low", "category": "style", "message": "nit"}]}\n```'
    assert len(parse_ai_findings(raw, allowed_files=ALLOWED)) == 1


def test_accepts_a_bare_list():
    raw = '[{"file": "app/main.py", "line": 3, "severity": "medium", "category": "style", "message": "x"}]'
    assert len(parse_ai_findings(raw, allowed_files=ALLOWED)) == 1


def test_accepts_alternate_keys_and_string_line_numbers():
    raw = '{"issues": [{"path": "app/main.py", "line": "17", "severity": "high", "category": "bug", "message": "x"}]}'
    drafts = parse_ai_findings(raw, allowed_files=ALLOWED)
    assert drafts[0].line_number == 17


def test_hallucinated_files_are_dropped():
    raw = '{"findings": [{"file": "app/does_not_exist.py", "line": 1, "severity": "high", "category": "bug", "message": "x"}]}'
    assert parse_ai_findings(raw, allowed_files=ALLOWED) == []


def test_unknown_severity_is_mapped():
    raw = '{"findings": [{"file": "app/main.py", "line": 1, "severity": "critical", "category": "bug", "message": "x"}]}'
    assert parse_ai_findings(raw, allowed_files=ALLOWED)[0].severity == "high"


def test_trailing_comma_is_tolerated():
    raw = '{"findings": [{"file": "app/main.py", "line": 1, "severity": "low", "category": "style", "message": "x",},]}'
    assert len(parse_ai_findings(raw, allowed_files=ALLOWED)) == 1


def test_line_zero_is_clamped_to_one():
    raw = '{"findings": [{"file": "app/main.py", "line": 0, "severity": "low", "category": "style", "message": "x"}]}'
    assert parse_ai_findings(raw, allowed_files=ALLOWED)[0].line_number == 1


def test_empty_list_is_valid():
    assert parse_ai_findings('{"findings": []}', allowed_files=ALLOWED) == []


def test_unparseable_response_raises():
    with pytest.raises(AIReviewError):
        parse_ai_findings("I could not review this diff, sorry!", allowed_files=ALLOWED)


def test_missing_api_key_degrades_gracefully():
    reviewer = AIReviewer(api_key="", model="gpt-4o-mini")
    result = reviewer.review("diff --git a/x b/x")
    assert result.skipped is True
    assert result.findings == []


def test_empty_diff_degrades_gracefully():
    reviewer = AIReviewer(api_key="sk-fake", model="gpt-4o-mini")
    result = reviewer.review("   ")
    assert result.skipped is True

"""Unit tests for pyflakes integration and the secret scanner."""

from __future__ import annotations

from app.services.static_analysis import filter_by_lines, mask_secret, run_pyflakes, scan_secrets


# --------------------------------------------------------------------------- #
# pyflakes
# --------------------------------------------------------------------------- #
def test_undefined_name_is_high_severity():
    drafts = run_pyflakes("demo.py", "print(undefined_name)\n")
    assert drafts, "pyflakes should report an undefined name"
    finding = drafts[0]
    assert finding.severity == "high"
    assert finding.category == "bug"
    assert "undefined name" in finding.message.lower()
    assert finding.source == "static"
    assert finding.line_number == 1


def test_unused_import_is_low_severity():
    drafts = run_pyflakes("demo.py", "import os\n\nx = 1\n")
    assert drafts
    assert drafts[0].severity == "low"
    assert drafts[0].category == "style"


def test_syntax_error_is_reported_not_raised():
    drafts = run_pyflakes("broken.py", "def oops(:\n    pass\n")
    assert drafts
    assert drafts[0].severity == "high"
    assert "syntax" in drafts[0].message.lower()


def test_clean_file_has_no_findings():
    assert run_pyflakes("clean.py", "def add(a, b):\n    return a + b\n") == []


def test_filter_by_lines_keeps_only_changed_lines():
    drafts = run_pyflakes("demo.py", "import os\n\nprint(undefined_name)\n")
    assert len(drafts) >= 2
    kept = filter_by_lines(drafts, {3})
    assert len(kept) == 1
    assert kept[0].line_number == 3


# --------------------------------------------------------------------------- #
# secret scanner
# --------------------------------------------------------------------------- #
def test_aws_key_is_detected_and_masked():
    drafts = scan_secrets("settings.py", {7: 'AWS_ACCESS_KEY_ID = "AKIAZ7XK2LMN4PQRS3TU"'})
    assert len(drafts) == 1
    assert drafts[0].severity == "high"
    assert drafts[0].category == "security"
    assert drafts[0].source == "secret"
    assert drafts[0].line_number == 7
    # The real key must not be echoed back to the PR.
    assert "AKIAZ7XK2LMN4PQRS3TU" not in drafts[0].message


def test_openai_key_is_detected():
    drafts = scan_secrets("config.py", {1: 'OPENAI_API_KEY = "sk-proj-abc123def456ghi789jkl012mno345pqr"'})
    assert drafts
    assert "OpenAI" in drafts[0].message


def test_generic_hardcoded_password_is_medium():
    drafts = scan_secrets("db.py", {12: 'password = "hunter2hunter2"'})
    assert drafts
    assert drafts[0].severity == "medium"
    assert "credential" in drafts[0].message.lower()


def test_placeholders_are_not_reported():
    lines = {
        1: 'password = "your-password-here"',
        2: 'api_key = os.getenv("OPENAI_API_KEY")',
        3: 'token = "changeme"',
        4: 'secret = settings.SECRET_KEY',
    }
    assert scan_secrets("config.py", lines) == []


def test_type_hints_are_not_secrets():
    assert scan_secrets("models.py", {3: "password: str"}) == []


def test_database_url_with_credentials_is_flagged():
    drafts = scan_secrets("db.py", {5: 'URL = "postgresql://admin:s3cretpass@db.internal:5432/app"'})
    assert drafts
    assert drafts[0].severity == "high"


def test_private_key_block_is_flagged():
    drafts = scan_secrets("id_rsa.py", {1: "KEY = '''-----BEGIN RSA PRIVATE KEY-----'''"})
    assert drafts
    assert drafts[0].severity == "high"


def test_only_one_finding_per_line():
    line = 'aws_secret_access_key = "AKIAZ7XK2LMN4PQRS3TU" password = "hunter2hunter2"'
    drafts = scan_secrets("conf.py", {1: line})
    assert len(drafts) == 1


def test_mask_secret_keeps_edges_only():
    masked = mask_secret("sk-proj-abcdefghijklmnop1234")
    assert masked.startswith("sk-p")
    assert masked.endswith("1234")
    assert "abcdefghijklmnop" not in masked

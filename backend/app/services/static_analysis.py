"""Static analysis: pyflakes (Python) + a regex secret scanner.

Both are intentionally cheap and offline. The AI is good at "this logic looks
wrong"; tools are good at "this name is undefined" and "this is an AWS key".
Using both is what makes the review credible in a demo.
"""

from __future__ import annotations

import re

from app.logging_config import get_logger
from app.models import Category, FindingSource, Severity
from app.services.findings import FindingDraft

logger = get_logger(__name__)

# --- limits that keep a single huge file from flooding the PR --------------- #
MAX_FILE_BYTES = 500_000
MAX_FINDINGS_PER_FILE = 25


# --------------------------------------------------------------------------- #
# pyflakes
# --------------------------------------------------------------------------- #
class _PyflakesCollector:
    """Adapter around pyflakes' Reporter API.

    pyflakes is designed to print to a stream; we hand it a StringIO and grab
    the messages instead, which keeps this dependency optional and the output
    structured.
    """

    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    # pyflakes calls these hooks ---------------------------------------- #
    def flake(self, message) -> None:  # noqa: ANN001 - pyflakes Message
        try:
            text = message.message % message.message_args
        except (AttributeError, TypeError):
            text = str(message)
        try:
            lineno = int(message.lineno)
        except (AttributeError, TypeError, ValueError):
            lineno = 1
        self.messages.append({"line": lineno, "text": text})

    def unexpectedError(self, filename, msg) -> None:  # noqa: N802 (API name)
        logger.warning("pyflakes internal error on %s: %s", filename, msg)

    def syntaxError(self, filename, msg, lineno, offset, text) -> None:  # noqa: N802
        self.messages.append(
            {"line": int(lineno or 1), "text": f"syntax error: {msg}"}
        )


def _classify_pyflakes(text: str) -> tuple[str, str, str | None]:
    """(severity, category, suggestion) for a pyflakes message."""
    lowered = text.lower()
    if "undefined name" in lowered:
        return (
            Severity.HIGH.value,
            Category.BUG.value,
            "This name is never imported or assigned. Add the import, or remove the reference.",
        )
    if "syntax error" in lowered:
        return (
            Severity.HIGH.value,
            Category.BUG.value,
            "The file does not parse. Fix the syntax before merging.",
        )
    if "imported but unused" in lowered:
        return (
            Severity.LOW.value,
            Category.STYLE.value,
            "Remove the unused import (or use it). It slows startup and confuses readers.",
        )
    if "assigned to but never used" in lowered or "local variable" in lowered:
        return (
            Severity.LOW.value,
            Category.STYLE.value,
            "Remove the variable, or use `_` if you must keep the assignment.",
        )
    if "redefinition of unused" in lowered or "shadow" in lowered:
        return (
            Severity.MEDIUM.value,
            Category.BUG.value,
            "This redefines an earlier name. Rename one of them to avoid confusion.",
        )
    if "unable to detect undefined names" in lowered or "star import" in lowered:
        return (
            Severity.LOW.value,
            Category.STYLE.value,
            "Avoid wildcard imports: they hide undefined names from static analysis.",
        )
    return (
        Severity.MEDIUM.value,
        Category.BUG.value,
        "Address the warning reported by pyflakes.",
    )


def run_pyflakes(file_path: str, source: str) -> list[FindingDraft]:
    """Lint one Python file's *new* content.

    Any exception inside pyflakes is swallowed: a crash in a linter must never
    take down an entire review job.
    """
    if len(source.encode("utf-8", errors="ignore")) > MAX_FILE_BYTES:
        logger.info("Skipping pyflakes for %s (file too large)", file_path)
        return []

    try:
        from pyflakes import api as pyflakes_api
    except ImportError:  # pragma: no cover - dependency is in requirements
        logger.warning("pyflakes is not installed; skipping Python static analysis")
        return []

    collector = _PyflakesCollector()
    try:
        pyflakes_api.check(source, file_path, reporter=collector)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - never let a linter crash the job
        logger.exception("pyflakes failed unexpectedly on %s", file_path)
        return []

    drafts: list[FindingDraft] = []
    seen: set[tuple[int, str]] = set()
    for item in collector.messages:
        line = int(item["line"])  # type: ignore[arg-type]
        text = str(item["text"]).strip()
        if not text or (line, text) in seen:
            continue
        seen.add((line, text))
        severity, category, suggestion = _classify_pyflakes(text)
        drafts.append(
            FindingDraft(
                file_path=file_path,
                line_number=line,
                severity=severity,
                category=category,
                message=text,
                suggestion=suggestion,
                source=FindingSource.STATIC.value,
            )
        )
        if len(drafts) >= MAX_FINDINGS_PER_FILE:
            break
    return drafts


# --------------------------------------------------------------------------- #
# Secret scanner
# --------------------------------------------------------------------------- #
class SecretPattern:
    __slots__ = ("name", "regex", "severity", "suggestion")

    def __init__(self, name: str, regex: str, severity: str, suggestion: str) -> None:
        self.name = name
        self.regex = re.compile(regex)
        self.severity = severity
        self.suggestion = suggestion


SECRET_PATTERNS: list[SecretPattern] = [
    SecretPattern(
        "OpenAI API key",
        r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}",
        Severity.HIGH.value,
        "Revoke this key in the OpenAI dashboard, then load it from `os.environ['OPENAI_API_KEY']`.",
    ),
    SecretPattern(
        "AWS access key ID",
        r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
        Severity.HIGH.value,
        "Revoke the key in IAM and use an IAM role or environment variable instead.",
    ),
    SecretPattern(
        "AWS secret access key",
        r"(?i)aws_?secret_?access_?key\s*[:=]\s*['\"][A-Za-z0-9/+=]{32,}['\"]",
        Severity.HIGH.value,
        "Revoke the key in IAM and load it from the environment at runtime.",
    ),
    SecretPattern(
        "GitHub token",
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b",
        Severity.HIGH.value,
        "Revoke the token in GitHub settings and inject it via an environment variable or Actions secret.",
    ),
    SecretPattern(
        "GitHub fine-grained token",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
        Severity.HIGH.value,
        "Revoke the token in GitHub settings and inject it via an environment variable.",
    ),
    SecretPattern(
        "Slack token",
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
        Severity.HIGH.value,
        "Revoke the token in your Slack app settings and store it server-side only.",
    ),
    SecretPattern(
        "Google API key",
        r"\bAIza[0-9A-Za-z_-]{35}\b",
        Severity.HIGH.value,
        "Restrict/rotate the key in Google Cloud Console and keep it server-side.",
    ),
    SecretPattern(
        "Stripe secret key",
        r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b",
        Severity.HIGH.value,
        "Roll the key in the Stripe dashboard. Publishable keys are fine in the browser; secret keys are not.",
    ),
    SecretPattern(
        "Private key block",
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
        Severity.HIGH.value,
        "Remove the private key from the repo and rotate it immediately. Treat it as compromised.",
    ),
    SecretPattern(
        "Database URL with credentials",
        r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/]+:[^\s@/]+@",
        Severity.HIGH.value,
        "Read the URL from an environment variable and rotate the database password.",
    ),
    SecretPattern(
        "JSON Web Token",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        Severity.MEDIUM.value,
        "Do not commit JWTs; they are bearer credentials until they expire.",
    ),
    SecretPattern(
        "Bearer token in header",
        r"(?i)authorization['\"]?\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9._\-]{20,}",
        Severity.HIGH.value,
        "Load the token from the environment / secret manager instead of hardcoding it.",
    ),
    SecretPattern(
        "credential",
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token|auth[_-]?token)\b"
        r"\s*[:=]\s*['\"]([^'\"]{8,})['\"]",
        Severity.MEDIUM.value,
        "Move the value into an environment variable and rotate it if it was real.",
    ),
]

# Values that look like secrets but are placeholders. Checked against the whole
# matched line: `password = os.getenv("X")` and `api_key = "your-key-here"`
# should not produce findings in every tutorial repo on Earth.
_PLACEHOLDER_HINTS = (
    "example",
    "changeme",
    "change-me",
    "change_me",
    "your_",
    "your-",
    "placeholder",
    "dummy",
    "fake",
    "sample",
    "xxxx",
    "****",
    "...",
    "<",
    ">",
    "${",
    "{{",
    "os.environ",
    "os.getenv",
    "getenv(",
    "process.env",
    "settings.",
    "config.",
    "none",
    "null",
    "todo",
)

# `password = "supersecret123"` is a finding; `password: str` is a type hint.
_TYPE_HINT_ONLY = re.compile(r"^\s*(?:password|secret|token|api_key)\w*\s*:\s*[A-Za-z_\[\]\.|]+\s*$")


def _looks_like_placeholder(line: str) -> bool:
    lowered = line.lower()
    return any(hint in lowered for hint in _PLACEHOLDER_HINTS)


def mask_secret(value: str) -> str:
    """`sk-proj-abcdef123456` -> `sk-p...(hidden)...3456`.

    We never echo a full credential into a PR comment, a log line or the UI:
    posting it would leak it further.
    """
    value = value.strip()
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...(hidden)...{value[-4:]}"


def redact_secrets(text: str) -> tuple[str, int]:
    """Redact credential-shaped values before code is sent to an AI provider."""
    redacted = text
    replacements = 0
    for pattern in SECRET_PATTERNS:
        redacted, count = pattern.regex.subn(f"[REDACTED {pattern.name}]", redacted)
        replacements += count
    return redacted, replacements


def scan_secrets(file_path: str, added_lines: dict[int, str]) -> list[FindingDraft]:
    """Scan only the lines this PR adds.

    Pre-existing secrets are not the reviewer's business here (and would spam
    every PR touching that file). Skipped for lockfiles/binary blobs by caller.
    """
    drafts: list[FindingDraft] = []
    seen_lines: set[int] = set()

    for line_number in sorted(added_lines):
        line = added_lines[line_number]
        if not line.strip() or _TYPE_HINT_ONLY.match(line):
            continue
        if _looks_like_placeholder(line):
            continue

        for pattern in SECRET_PATTERNS:
            match = pattern.regex.search(line)
            if not match:
                continue
            # One finding per line: the most specific pattern wins because
            # SECRET_PATTERNS is ordered from specific to generic.
            if line_number in seen_lines:
                break
            seen_lines.add(line_number)
            snippet = match.group(0)
            drafts.append(
                FindingDraft(
                    file_path=file_path,
                    line_number=line_number,
                    severity=pattern.severity,
                    category=Category.SECURITY.value,
                    message=f"Possible hardcoded {pattern.name}: `{mask_secret(snippet)}`",
                    suggestion=pattern.suggestion,
                    source=FindingSource.SECRET.value,
                )
            )
            break
        if len(drafts) >= MAX_FINDINGS_PER_FILE:
            break

    return drafts


def filter_by_lines(drafts: list[FindingDraft], allowed: set[int]) -> list[FindingDraft]:
    """Keep only findings anchored to a line present in the diff."""
    return [d for d in drafts if d.line_number in allowed]

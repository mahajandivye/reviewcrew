"""Custom review rules - the "custom linter" layer.

Rules are plain regexes with a message and a severity, stored as JSON in the
settings table so they need no schema change and can be edited from the UI.
They run on added lines, next to pyflakes and the secret scanner.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select

from app.logging_config import get_logger
from app.models import Category, FindingSource, Setting, Severity
from app.services.findings import FindingDraft

logger = get_logger(__name__)

SETTING_KEY = "custom_rules"
MAX_RULES = 50
MAX_LINE_MATCHES = 20

VALID_SEVERITIES = {item.value for item in Severity}
VALID_CATEGORIES = {item.value for item in Category}


class RuleError(ValueError):
    """Raised when a submitted rule is not usable."""


def _validate(raw: dict, index: int) -> dict:
    name = str(raw.get("name") or "").strip()[:80]
    pattern = str(raw.get("pattern") or "").strip()
    message = str(raw.get("message") or "").strip()[:400]
    severity = str(raw.get("severity") or "medium").lower()
    category = str(raw.get("category") or "bug").lower()
    enabled = bool(raw.get("enabled", True))

    if not name:
        raise RuleError(f"Rule #{index + 1}: a name is required.")
    if not pattern:
        raise RuleError(f"Rule #{index + 1}: a regex pattern is required.")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise RuleError(f"Rule #{index + 1}: invalid regex - {exc}") from exc
    if severity not in VALID_SEVERITIES:
        raise RuleError(f"Rule #{index + 1}: severity must be high, medium or low.")
    if category not in VALID_CATEGORIES:
        raise RuleError(f"Rule #{index + 1}: category must be bug, security or style.")
    if not message:
        message = f"Violates the project rule: {name}"

    return {
        "name": name,
        "pattern": pattern,
        "message": message,
        "severity": severity,
        "category": category,
        "enabled": enabled,
    }


def load_rules(db) -> list[dict]:  # noqa: ANN001
    row = db.get(Setting, SETTING_KEY)
    if row is None or not row.value:
        return []
    try:
        data = json.loads(row.value)
    except json.JSONDecodeError:
        logger.warning("custom_rules is not valid JSON; ignoring it")
        return []
    return [item for item in data if isinstance(item, dict)]


def save_rules(db, rules: list[dict]) -> list[dict]:  # noqa: ANN001
    if len(rules) > MAX_RULES:
        raise RuleError(f"A maximum of {MAX_RULES} rules is supported.")
    cleaned = [_validate(rule, index) for index, rule in enumerate(rules)]

    row = db.get(Setting, SETTING_KEY)
    if row is None:
        row = Setting(key=SETTING_KEY, value=json.dumps(cleaned), is_secret=False)
        db.add(row)
    else:
        row.value = json.dumps(cleaned)
    db.commit()
    return cleaned


def apply_rules(
    file_path: str, added_lines: dict[int, str], rules: list[dict]
) -> list[FindingDraft]:
    """Run every enabled rule over the lines this change added."""
    drafts: list[FindingDraft] = []
    compiled = []
    for rule in rules:
        if not rule.get("enabled"):
            continue
        try:
            compiled.append((rule, re.compile(str(rule["pattern"]))))
        except (re.error, KeyError):
            continue

    for line_number in sorted(added_lines):
        line = added_lines[line_number]
        if not line.strip():
            continue
        for rule, pattern in compiled:
            if not pattern.search(line):
                continue
            drafts.append(
                FindingDraft(
                    file_path=file_path,
                    line_number=line_number,
                    severity=str(rule.get("severity") or "medium"),
                    category=str(rule.get("category") or "bug"),
                    message=str(rule.get("message") or f"Violates rule: {rule.get('name')}"),
                    suggestion=f"Adjust this line so it satisfies the rule \"{rule.get('name')}\".",
                    source=FindingSource.RULE.value,
                )
            )
            if len(drafts) >= MAX_LINE_MATCHES:
                return drafts

    return drafts

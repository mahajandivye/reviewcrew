"""Generate a runnable test file for the reviewed code.

One extra model call, on demand. Unit tests are the thing developers most often
skip, so "Generate tests" next to a review is a concrete time saver.
"""

from __future__ import annotations

import json
import re

from app.logging_config import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You write tests, not advice.

Given source code and a list of review findings, write ONE complete test file
with pytest that:
1. Covers the risky behaviour the findings describe (injection, None handling,
   empty input, boundary values, resource cleanup).
2. Uses only the standard library plus pytest. Do not invent fixtures or helper
   modules that were not provided.
3. Imports the code under test with an explicit module path comment when the
   real import path is unknown, e.g. `from app.db import get_user  # adjust path`.
4. Is runnable as-is: `pytest test_<name>.py`.

Return a single fenced code block tagged ```python and nothing else."""


def _clean(text: str) -> str:
    match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def generate_tests(
    *,
    api_key: str,
    model: str,
    base_url: str | None,
    code_by_file: dict[str, str],
    findings: list[dict],
    title: str = "",
    timeout: float = 90.0,
) -> str:
    """Return the test file source. Raises RuntimeError on provider failure."""
    from openai import OpenAI

    files_block = "\n\n".join(
        f"### {path}\n```\n{code[:6000]}\n```" for path, code in sorted(code_by_file.items())
    )
    finding_lines = "\n".join(
        f"- [{item.get('severity')}/{item.get('category')}] "
        f"{item.get('file_path')}:{item.get('line_number')} {item.get('message')}"
        for item in findings[:15]
    ) or "- (none)"

    user = (
        f"Review title: {title or 'code review'}\n\n"
        f"Source:\n{files_block}\n\n"
        f"Findings to cover:\n{finding_lines}\n\n"
        "Write the test file now."
    )

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=1800,
        )
    except Exception as exc:  # noqa: BLE001 - provider errors vary
        logger.warning("Test generation failed: %s", exc)
        raise RuntimeError(f"the model provider rejected the request: {exc}") from exc

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("the model returned an empty test file")

    logger.info("Generated tests (%d chars)", len(content))
    return _clean(content)


def build_findings_payload(findings) -> list[dict]:  # noqa: ANN001
    return [
        {
            "severity": finding.severity,
            "category": finding.category,
            "file_path": finding.file_path,
            "line_number": finding.line_number,
            "message": finding.message,
        }
        for finding in findings
    ]


def _json_dumps(value) -> str:  # noqa: ANN001
    return json.dumps(value, ensure_ascii=False)

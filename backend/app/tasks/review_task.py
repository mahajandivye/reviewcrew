"""THE review pipeline (Celery task).

End-to-end flow of `run_review(review_id)`:

    load Review -> status=running
    GitHub: fetch PR metadata + changed files
    build a unified diff -> store it on the Review
    pyflakes on changed .py files  -> findings
    secret scanner on added lines  -> findings
    OpenAI on the diff             -> findings
    persist Findings
    post inline comments back to the PR
    status=completed (or failed, with the error stored for the dashboard)

Why a task and not the webhook handler: fetching a diff + 60s of LLM work would
blow past GitHub's webhook timeout. The webhook only enqueues.

Every step is wrapped so a failure is *recorded*, never swallowed: the
dashboard must always be able to show why a review failed.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone

from celery.exceptions import SoftTimeLimitExceeded

from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.logging_config import get_logger
from app.models import Finding, Review, ReviewStatus
from app.services.ai_reviewer import AIReviewError, AIReviewer
from app.services.diff_parser import (
    added_lines_by_file,
    build_diff_text,
    commentable_lines_by_file,
    is_python,
    parse_unified_diff,
)
from app.services.findings import FindingDraft, dedupe_findings, rank_findings
from app.services.github_service import GitHubClient, GitHubError
from app.services.rules_service import apply_rules, load_rules
from app.services.settings_service import get_effective_settings
from app.services.static_analysis import filter_by_lines, redact_secrets, run_pyflakes, scan_secrets

logger = get_logger(__name__)

SEVERITY_EMOJI = {"high": "🔴", "medium": "🟠", "low": "🔵"}
SOURCE_LABEL = {"ai": "AI", "static": "pyflakes", "secret": "secret scan"}

# GitHub's hard limit for a comment body is 65536 chars.
MAX_COMMENT_BODY = 60_000
MAX_INLINE_COMMENTS = 30

# Files where a regex hit is almost always noise (generated/minified/lockfiles).
_SECRET_SCAN_SKIP_SUFFIXES = (
    ".lock",
    ".min.js",
    ".min.css",
    ".map",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
)
_SECRET_SCAN_SKIP_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
}


class ReviewError(RuntimeError):
    """A review cannot continue (bad config, unreadable PR, ...)."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def enqueue_review(review_id: int) -> str | None:
    """Public helper used by the webhook and the retry endpoint.

    `.delay()` serialises the argument to JSON and pushes it to Redis; the
    API process does NOT wait for the work.
    """
    result = run_review.delay(review_id)
    task_id = getattr(result, "id", None)
    logger.info("Enqueued review %s (celery task id=%s)", review_id, task_id)
    return task_id


@celery_app.task(bind=True, name="reviewpilot.run_review")
def run_review(self, review_id: int) -> dict[str, object]:  # noqa: ANN001
    """Review one PR. Returns plain data (Celery stores it as JSON)."""
    started = time.perf_counter()
    logger.info("=== review %s: START ===", review_id)

    db = SessionLocal()
    try:
        review = db.get(Review, review_id)
        if review is None:
            logger.error("review %s: row not found - was the database reset?", review_id)
            return {"status": "missing", "review_id": review_id}

        # Idempotency guard: a redelivered Celery message must not re-review.
        if review.status == ReviewStatus.COMPLETED.value:
            logger.info("review %s: already completed, skipping", review_id)
            return {"status": "already_completed", "review_id": review_id}

        review.status = ReviewStatus.RUNNING.value
        review.started_at = _utcnow()
        review.error_message = None
        db.commit()
        logger.info(
            "review %s: %s#%s @ %s", review_id, review.repo_name, review.pr_number, review.head_sha[:8]
        )

        # --- 1. configuration ------------------------------------------- #
        effective = get_effective_settings(db)
        source = review.source or "github"
        client: GitHubClient | None = None
        pr = None

        if source == "github":
            # Anonymous access is fine for public repos; a token adds private
            # repos, comment posting and a higher rate limit.
            client = GitHubClient(effective.github_token)

            # --- 2. fetch the PR ---------------------------------------- #
            try:
                pr = client.collect_pr(review.repo_name, review.pr_number)
            except GitHubError as exc:
                raise ReviewError(
                    f"Could not read {review.repo_name}#{review.pr_number}: {exc}. "
                    "If this is a private repository, add a GitHub token in Settings."
                ) from exc
            review.pr_title = pr.title or review.pr_title
            review.pr_url = pr.url or review.pr_url
            review.head_sha = pr.head_sha or review.head_sha
            review.pr_author = pr.author or review.pr_author
            review.files_changed = len(pr.files)
            review.additions = pr.total_additions
            review.deletions = pr.total_deletions
            db.commit()
            logger.info(
                "review %s: fetched %d changed file(s), +%d/-%d",
                review_id,
                len(pr.files),
                pr.total_additions,
                pr.total_deletions,
            )

            # --- 3. build + store the diff ------------------------------ #
            diff_text = build_diff_text(
                [
                    {
                        "path": f.path,
                        "old_path": f.previous_path,
                        "patch": f.patch,
                        "status": f.status,
                    }
                    for f in pr.files
                ]
            )
            review.diff_text = diff_text[:2_000_000]  # 2 MB safety cap
            db.commit()
        else:
            # Pasted diff / pasted file: the diff was built when the review was
            # created, so there is nothing to fetch and nobody to comment on.
            diff_text = review.diff_text
            logger.info(
                "review %s: local %s review (%d bytes)", review_id, source, len(diff_text)
            )

        parsed_files = parse_unified_diff(diff_text)
        added_lines = added_lines_by_file(parsed_files)
        commentable = commentable_lines_by_file(parsed_files)
        logger.info(
            "review %s: parsed %d file(s) from the diff (%d bytes)",
            review_id,
            len(parsed_files),
            len(diff_text),
        )

        drafts: list[FindingDraft] = []
        warnings: list[str] = []

        # --- 4. pyflakes on changed Python files ------------------------ #
        # For GitHub reviews we fetch the file at the head commit. For pasted
        # code the full file is already in the diff (every line is an addition),
        # so it can be reconstructed without any network call. Pasted *diffs*
        # only contain hunks, so pyflakes is skipped there to avoid reporting
        # false "undefined name" errors caused by missing context.
        local_sources: dict[str, str] = {}
        if source in {"code", "files"}:
            for path, lines in added_lines.items():
                local_sources[path] = "\n".join(lines[line] for line in sorted(lines))

        for path in sorted(added_lines):
            if not is_python(path):
                continue
            file_source: str | None = local_sources.get(path)
            if file_source is None and client is not None and pr is not None:
                file_source = client.get_file_content(review.repo_name, path, pr.head_sha)
            if file_source is None:
                continue
            file_drafts = run_pyflakes(path, file_source)
            # Only comment on lines the PR actually touched: pre-existing
            # lint noise in a 900-line file is not this PR's problem.
            kept = filter_by_lines(file_drafts, set(added_lines.get(path, {})))
            logger.info(
                "review %s: pyflakes %s -> %d finding(s) on changed lines (of %d total)",
                review_id,
                path,
                len(kept),
                len(file_drafts),
            )
            drafts.extend(kept)

        # --- 5. secret scanner on added lines --------------------------- #
        scanned = 0
        for path, lines in added_lines.items():
            if not _should_scan_for_secrets(path):
                continue
            scanned += 1
            drafts.extend(scan_secrets(path, lines))
        logger.info(
            "review %s: secret scan covered %d file(s), %d finding(s)",
            review_id,
            scanned,
            sum(1 for d in drafts if d.source == "secret"),
        )

        # --- 5b. user-defined rules ------------------------------------- #
        rules = load_rules(db)
        if rules:
            for path, lines in added_lines.items():
                drafts.extend(apply_rules(path, lines, rules))
            logger.info(
                "review %s: custom rules -> %d finding(s)",
                review_id,
                sum(1 for d in drafts if d.source == "rule"),
            )

        # --- 6. AI review ----------------------------------------------- #
        ai_note: str | None = None
        tokens_used = 0
        try:
            ai = AIReviewer(
                api_key=effective.openai_api_key,
                model=effective.openai_model,
                base_url=effective.openai_base_url,
                persona=effective.reviewer_persona,
            )
            safe_diff, redacted_count = redact_secrets(diff_text)
            if redacted_count:
                logger.info("review %s: redacted %d secret-shaped value(s) before AI review", review_id, redacted_count)
                # Keep stored diff previews safe too; raw lines were already used
                # by the local scanner above and are never written to logs.
                review.diff_text = safe_diff[:2_000_000]
                db.commit()
            ai_result = ai.review(
                safe_diff,
                repo_name=review.repo_name,
                pr_title=review.pr_title,
                changed_files=sorted(added_lines) or [f.path for f in parsed_files],
            )
            tokens_used = ai_result.tokens_used
            if ai_result.skipped:
                ai_note = f"AI review skipped: {ai_result.skipped_reason}."
                logger.warning("review %s: %s", review_id, ai_note)
            else:
                drafts.extend(ai_result.findings)
                logger.info(
                    "review %s: AI returned %d finding(s)", review_id, len(ai_result.findings)
                )
        except AIReviewError as exc:
            # Static analysis results are still valuable - do not fail the job.
            ai_note = f"AI review failed: {exc}"
            logger.warning("review %s: %s", review_id, ai_note)

        # --- 7. persist findings ---------------------------------------- #
        # Normalise -> remove duplicates -> most severe first -> cap.
        # Capping last means we keep the worst 50, not the first 50 we saw.
        before = len(drafts)
        drafts = [d.normalised() for d in drafts]
        drafts = rank_findings(dedupe_findings(drafts))
        drafts = drafts[: settings.max_findings]
        if len(drafts) < before:
            logger.info(
                "review %s: %d duplicate(s) removed, %d finding(s) kept",
                review_id,
                before - len(drafts),
                len(drafts),
            )

        # Retries/re-runs start clean.
        db.query(Finding).filter(Finding.review_id == review.id).delete()

        for draft in drafts:
            # Snapshot the line the finding refers to, so the UI can show a
            # before/after diff later without re-reading the source.
            snippet = added_lines.get(draft.file_path, {}).get(draft.line_number)
            safe_snippet = redact_secrets(snippet or "")[0]
            db.add(
                Finding(
                    review_id=review.id,
                    file_path=draft.file_path,
                    line_number=draft.line_number,
                    severity=draft.severity,
                    category=draft.category,
                    message=draft.message,
                    suggestion=draft.suggestion,
                    source=draft.source,
                    original_snippet=safe_snippet[:800] or None,
                    evidence=redact_secrets(draft.evidence or safe_snippet)[0][:1000] or None,
                    confidence=draft.confidence if draft.source == "ai" else 0.98,
                )
            )
        review.tokens_used = tokens_used or None
        if ai_note:
            review.error_message = ai_note[:2000]
        db.commit()
        logger.info("review %s: persisted %d finding(s)", review_id, len(drafts))

        # --- 8. post back to GitHub ------------------------------------- #
        # Only real PRs get comments, and only when a token is configured:
        # anonymous access is read-only. Pasted code has no PR at all.
        can_post = (
            source == "github"
            and client is not None
            and pr is not None
            and bool(effective.github_token)
        )
        if source == "github" and not effective.github_token:
            warnings.append("Reviewed without a GitHub token - comments were not posted.")
            logger.info("review %s: no token, skipping comment posting", review_id)
        if can_post and effective.post_pr_comments and drafts:
            try:
                inline, overflow = _build_inline_comments(drafts, commentable)
                body = _build_summary_body(
                    review,
                    drafts,
                    inline_count=len(inline),
                    overflow=overflow,
                    ai_note=ai_note,
                )
                url = client.post_review(
                    review.repo_name,
                    review.pr_number,
                    body=body,
                    comments=inline,
                    commit_sha=pr.head_sha,
                )
                review.github_review_url = url
                db.commit()
                logger.info(
                    "review %s: posted %d inline comment(s) + summary -> %s",
                    review_id,
                    len(inline),
                    url,
                )
                if overflow:
                    logger.info(
                        "review %s: %d finding(s) mentioned in the summary instead of inline",
                        review_id,
                        len(overflow),
                    )
            except GitHubError as exc:
                # Posting is best-effort: the review is still valuable in the UI.
                warnings.append(f"Could not post comments to GitHub: {exc}")
                logger.warning("review %s: %s", review_id, warnings[-1])
        elif source != "github":
            logger.info("review %s: local review, nothing to post to GitHub", review_id)
        elif not effective.post_pr_comments:
            logger.info("review %s: POST_PR_COMMENTS is disabled, not commenting", review_id)

        # --- 9. finish --------------------------------------------------- #
        review.status = ReviewStatus.COMPLETED.value
        review.completed_at = _utcnow()
        review.duration_ms = int((time.perf_counter() - started) * 1000)
        if warnings:
            existing = review.error_message or ""
            review.error_message = "; ".join([existing, *warnings]).strip("; ")[:2000]
        db.commit()

        logger.info(
            "=== review %s: COMPLETE in %.2fs with %d finding(s) ===",
            review_id,
            review.duration_ms / 1000.0,
            len(drafts),
        )
        return {
            "status": "completed",
            "review_id": review_id,
            "findings": len(drafts),
            "duration_ms": review.duration_ms,
            "tokens_used": tokens_used,
        }

    except SoftTimeLimitExceeded:
        _mark_failed(review_id, "Review timed out (Celery soft time limit).")
        logger.error("review %s: timed out", review_id)
        return {"status": "failed", "review_id": review_id, "error": "timeout"}
    except ReviewError as exc:
        _mark_failed(review_id, str(exc))
        logger.error("review %s: failed - %s", review_id, exc)
        return {"status": "failed", "review_id": review_id, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - last line of defence
        logger.exception("review %s: unexpected failure", review_id)
        _mark_failed(review_id, f"Unexpected error: {type(exc).__name__}: {exc}")
        return {
            "status": "failed",
            "review_id": review_id,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _should_scan_for_secrets(path: str) -> bool:
    lowered = path.lower()
    if lowered.rsplit("/", 1)[-1] in _SECRET_SCAN_SKIP_NAMES:
        return False
    return not lowered.endswith(_SECRET_SCAN_SKIP_SUFFIXES)


def _build_inline_comments(
    drafts: list[FindingDraft], commentable: dict[str, set[int]]
) -> tuple[list[dict[str, object]], list[FindingDraft]]:
    """Split findings into inline comments vs. summary-only.

    GitHub rejects (422) a comment whose `line` is not part of the diff, and
    limits how many comments one review can carry. Both are handled here:
    commentable lines go inline (up to MAX_INLINE_COMMENTS), the rest are
    listed in the review body so nothing is silently dropped.
    """
    inline: list[dict[str, object]] = []
    overflow: list[FindingDraft] = []

    for draft in drafts:
        allowed = commentable.get(draft.file_path, set())
        if draft.line_number in allowed and len(inline) < MAX_INLINE_COMMENTS:
            inline.append(
                {
                    "path": draft.file_path,
                    "line": draft.line_number,
                    "side": "RIGHT",  # RIGHT = the new version of the file
                    "body": _format_inline_comment(draft),
                }
            )
        else:
            overflow.append(draft)

    return inline, overflow


def _format_inline_comment(draft: FindingDraft) -> str:
    emoji = SEVERITY_EMOJI.get(draft.severity, "🔵")
    source = SOURCE_LABEL.get(draft.source, draft.source)
    parts = [f"{emoji} **{draft.severity.upper()} · {draft.category}** — _{source}_", "", draft.message]
    if draft.suggestion:
        parts += ["", "**Suggestion**", draft.suggestion]
    return "\n".join(parts)[:MAX_COMMENT_BODY]


def _build_summary_body(
    review: Review,
    drafts: list[FindingDraft],
    *,
    inline_count: int,
    overflow: list[FindingDraft],
    ai_note: str | None,
) -> str:
    counts = Counter(d.severity for d in drafts)
    lines = [
        "## 🤖 ReviewPilot review",
        "",
        f"Found **{len(drafts)}** issue(s) across **{review.files_changed}** changed file(s): "
        f"🔴 {counts.get('high', 0)} high · 🟠 {counts.get('medium', 0)} medium · "
        f"🔵 {counts.get('low', 0)} low.",
    ]
    if inline_count:
        lines.append("")
        lines.append(f"Details are attached as {inline_count} inline comment(s) on the diff.")
    if ai_note:
        lines += ["", f"> ⚠️ {ai_note}"]

    if overflow:
        lines += ["", "### Other findings", ""]
        for d in overflow[:20]:
            emoji = SEVERITY_EMOJI.get(d.severity, "🔵")
            lines.append(f"- {emoji} `{d.file_path}:{d.line_number}` — {d.message}")

    lines += [
        "",
        "---",
        "_Generated by ReviewPilot · pyflakes + secret scanner + AI. "
        "Verify before applying: automated reviews can be wrong._",
    ]
    return "\n".join(lines)[:MAX_COMMENT_BODY]


def _mark_failed(review_id: int, message: str) -> None:
    """Record a failure in its own session.

    This must not depend on the outer session, which may be in a broken state
    after an exception. If even this fails, we only log - there is nothing
    better left to do.
    """
    db = SessionLocal()
    try:
        review = db.get(Review, review_id)
        if review is None:
            return
        review.status = ReviewStatus.FAILED.value
        review.error_message = (message or "Unknown error")[:2000]
        review.completed_at = _utcnow()
        if review.started_at is not None:
            started_at = review.started_at
            # SQLite drops tzinfo, Postgres keeps it. Normalise before
            # subtracting, otherwise the naive/aware mix raises TypeError.
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            review.duration_ms = int(
                (review.completed_at - started_at).total_seconds() * 1000
            )
        # Drop partial results: a failed review should not look half-successful.
        db.query(Finding).filter(Finding.review_id == review_id).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Could not mark review %s as failed", review_id)
    finally:
        db.close()

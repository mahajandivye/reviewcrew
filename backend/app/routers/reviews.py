"""Review history endpoints.

  GET  /api/reviews             -> paginated list (dashboard table)
  GET  /api/reviews/{id}        -> full detail with findings
  GET  /api/reviews/{id}/diff   -> structured diff for the split viewer
  POST /api/reviews/{id}/retry  -> re-queue a failed review (demo life-saver)
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.logging_config import get_logger
from app.models import SEVERITY_RANK, Finding, Review, ReviewStatus
from app.schemas import (
    DiffFileOut,
    DiffHunkOut,
    DiffLineOut,
    FindingOut,
    ReviewCreateRequest,
    ReviewDetail,
    ReviewDiffResponse,
    ReviewListResponse,
    ReviewSummary,
    TestsOut,
)
from app.services.code_context import added_code_by_file
from app.services.diff_parser import build_diff_text, parse_unified_diff
from app.services.github_service import GitHubClient, GitHubError
from app.services.metrics import analyse as analyse_metrics
from app.services.settings_service import get_effective_settings
from app.services.test_generator import build_findings_payload, generate_tests
from app.tasks.review_task import enqueue_review

logger = get_logger(__name__)
router = APIRouter(prefix="/reviews", tags=["reviews"])

# https://github.com/owner/repo/pull/123 (trailing /files, ?query etc. allowed)
PR_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/pull/(?P<number>\d+)"
)

# Pasted reviews are not real PRs, so they get a synthetic identity that still
# satisfies the (repo, pr_number, head_sha) unique constraint.
PASTED_DIFF_REPO = "pasted/diff"
PASTED_CODE_REPO = "pasted/code"
PASTED_FILES_REPO = "pasted/files"


def _summary(review: Review, findings_count: int = 0, high_count: int = 0) -> ReviewSummary:
    return ReviewSummary(
        id=review.id,
        repo_name=review.repo_name,
        pr_number=review.pr_number,
        pr_title=review.pr_title,
        pr_url=review.pr_url,
        status=review.status,
        source=review.source,
        files_changed=review.files_changed,
        findings_count=findings_count,
        high_severity_count=high_count,
        duration_seconds=(review.duration_ms / 1000.0) if review.duration_ms is not None else None,
        created_at=review.created_at,
        completed_at=review.completed_at,
    )


@router.get("", response_model=ReviewListResponse, summary="List reviews")
def list_reviews(
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(
        default=None, alias="status", description="queued|running|completed|failed"
    ),
    repo: str | None = Query(default=None, max_length=255, description="Filter by repo name"),
    q: str | None = Query(default=None, max_length=200, description="Search PR title or repo"),
    db: Session = Depends(get_db),
) -> ReviewListResponse:
    filters = []
    if status_filter:
        valid = {s.value for s in ReviewStatus}
        if status_filter not in valid:
            raise HTTPException(
                # Literal 422: FastAPI renamed this constant across versions.
                status_code=422,
                detail=f"status must be one of {sorted(valid)}",
            )
        filters.append(Review.status == status_filter)
    if repo:
        filters.append(Review.repo_name.ilike(f"%{repo}%"))
    if q:
        pattern = f"%{q}%"
        filters.append(or_(Review.pr_title.ilike(pattern), Review.repo_name.ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(Review).where(*filters)) or 0

    # One query for a page of reviews AND their finding counts. Doing this
    # per-row (N+1 queries) is the classic dashboard performance mistake.
    finding_count = func.count(Finding.id)
    high_count = func.coalesce(
        func.sum(case((Finding.severity == "high", 1), else_=0)), 0
    )

    rows = db.execute(
        select(Review, finding_count, high_count)
        .outerjoin(Finding, Finding.review_id == Review.id)
        .where(*filters)
        .group_by(Review.id)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [_summary(review, int(fc or 0), int(hc or 0)) for review, fc, hc in rows]
    pages = (total + page_size - 1) // page_size if total else 0

    return ReviewListResponse(
        items=items, total=total, page=page, page_size=page_size, pages=pages
    )


@router.get("/{review_id}", response_model=ReviewDetail, summary="Get one review")
def get_review(review_id: int, db: Session = Depends(get_db)) -> ReviewDetail:
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    findings = sorted(
        review.findings,
        key=lambda f: (SEVERITY_RANK.get(f.severity, 99), f.file_path, f.line_number),
    )
    counts = Counter(f.severity for f in findings)

    return ReviewDetail(
        **_summary(review, findings_count=len(findings), high_count=counts.get("high", 0)).model_dump(),
        pr_author=review.pr_author,
        head_sha=review.head_sha,
        additions=review.additions,
        deletions=review.deletions,
        error_message=review.error_message,
        github_review_url=review.github_review_url,
        started_at=review.started_at,
        generated_tests=review.generated_tests,
        counts_by_severity={
            "high": counts.get("high", 0),
            "medium": counts.get("medium", 0),
            "low": counts.get("low", 0),
        },
        findings=[FindingOut.model_validate(f) for f in findings],
    )


@router.get(
    "/{review_id}/diff",
    response_model=ReviewDiffResponse,
    summary="Structured diff for one review",
)
def get_review_diff(review_id: int, db: Session = Depends(get_db)) -> ReviewDiffResponse:
    """Parse the stored unified diff into hunks the split viewer can render.

    The diff is stored at review time, so this keeps working after a
    force-push, after the GitHub token expires, and on a machine with no
    network access - which matters during a live demo.
    """
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    if not review.diff_text.strip():
        return ReviewDiffResponse(review_id=review.id, has_diff=False, files=[])

    try:
        parsed = parse_unified_diff(review.diff_text)
    except Exception as exc:  # noqa: BLE001 - never 500 on a corrupt stored diff
        logger.exception("Could not parse stored diff for review %s", review_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The stored diff for this review could not be parsed.",
        ) from exc

    files: list[DiffFileOut] = []
    for file_diff in parsed:
        additions, deletions = file_diff.stats()
        files.append(
            DiffFileOut(
                path=file_diff.path,
                old_path=file_diff.old_path,
                status=file_diff.status,
                language=file_diff.language,
                additions=additions,
                deletions=deletions,
                is_binary=file_diff.is_binary,
                hunks=[
                    DiffHunkOut(
                        header=hunk.header,
                        old_start=hunk.old_start,
                        old_count=hunk.old_count,
                        new_start=hunk.new_start,
                        new_count=hunk.new_count,
                        section=hunk.section,
                        lines=[
                            DiffLineOut(
                                kind=line.kind,
                                old_line=line.old_line,
                                new_line=line.new_line,
                                content=line.content,
                            )
                            for line in hunk.lines
                        ],
                    )
                    for hunk in file_diff.hunks
                ],
            )
        )

    return ReviewDiffResponse(review_id=review.id, has_diff=bool(files), files=files)


@router.post(
    "/{review_id}/retry",
    response_model=ReviewSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-queue a review",
)
def retry_review(review_id: int, db: Session = Depends(get_db)) -> ReviewSummary:
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    if review.status in {ReviewStatus.QUEUED.value, ReviewStatus.RUNNING.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This review is already queued or running.",
        )

    # Clear stale results so a retry never mixes old and new findings.
    db.execute(delete(Finding).where(Finding.review_id == review.id))
    review.status = ReviewStatus.QUEUED.value
    review.error_message = None
    review.started_at = None
    review.completed_at = None
    review.duration_ms = None
    review.github_review_url = None
    db.commit()
    db.refresh(review)

    try:
        enqueue_review(review.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not re-enqueue review %s", review.id)
        review.status = ReviewStatus.FAILED.value
        review.error_message = f"Could not queue the job: {exc}"[:2000]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker queue unavailable. Is Redis running?",
        ) from exc

    return _summary(review)


@router.post(
    "",
    response_model=ReviewSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Start a review from the app (PR URL, pasted diff or pasted code)",
)
def create_review(
    payload: ReviewCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> ReviewSummary:
    """The self-serve entry point.

    Before this existed, a review could only start from a GitHub webhook: the
    platform was a bot, not a product. Now all three sources feed the exact
    same pipeline (diff parsing -> pyflakes -> secrets -> AI -> findings), so
    the dashboard behaves identically however the code arrived.
    """
    if payload.source == "pr":
        review = _review_from_pr_url(payload, db)
    elif payload.source == "diff":
        review = _review_from_diff(payload, db)
    elif payload.source == "files":
        review = _review_from_files(payload, db)
    else:
        review = _review_from_code(payload, db)

    # Reuse an existing review instead of duplicating work for the same commit.
    if review.status != ReviewStatus.QUEUED.value:
        response.status_code = status.HTTP_200_OK
        findings_count = db.scalar(
            select(func.count(Finding.id)).where(Finding.review_id == review.id)
        ) or 0
        high_count = db.scalar(
            select(func.count(Finding.id)).where(
                Finding.review_id == review.id, Finding.severity == "high"
            )
        ) or 0
        return _summary(review, int(findings_count), int(high_count))

    try:
        enqueue_review(review.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not enqueue review %s", review.id)
        review.status = ReviewStatus.FAILED.value
        review.error_message = f"Could not queue the job: {exc}"[:2000]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker queue unavailable. Is Redis running?",
        ) from exc

    # With CELERY_TASK_ALWAYS_EAGER the job already finished inside .delay(),
    # so refresh to return the real status instead of a stale "queued".
    db.refresh(review)
    findings_count = db.scalar(
        select(func.count(Finding.id)).where(Finding.review_id == review.id)
    ) or 0
    high_count = db.scalar(
        select(func.count(Finding.id)).where(
            Finding.review_id == review.id, Finding.severity == "high"
        )
    ) or 0
    return _summary(review, int(findings_count), int(high_count))


def _review_from_pr_url(payload: ReviewCreateRequest, db: Session) -> Review:
    """Queue a review for a real GitHub PR, without waiting for a webhook."""
    url = (payload.pr_url or "").strip()
    match = PR_URL_RE.match(url)
    if not match:
        raise HTTPException(
            status_code=422,
            detail="Expected a URL like https://github.com/owner/repo/pull/123",
        )

    repo_name = f"{match.group('owner')}/{match.group('repo')}"
    pr_number = int(match.group("number"))

    effective = get_effective_settings(db)

    # No token required for public pull requests: GitHub serves them
    # anonymously. A token is added automatically when one is configured, which
    # unlocks private repos, comment posting and a much higher rate limit.
    try:
        pr = GitHubClient(effective.github_token).get_pull_request(repo_name, pr_number)
        head_sha = pr.head.sha
        title = pr.title or f"Pull request #{pr_number}"
        author = pr.user.login if pr.user else None
        html_url = pr.html_url
    except GitHubError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"GitHub could not load that pull request: {exc}. "
                "Private repositories (and anonymous rate limits) need a GitHub "
                "token in Settings."
            ),
        ) from exc

    existing = db.execute(
        select(Review).where(
            Review.repo_name == repo_name,
            Review.pr_number == pr_number,
            Review.head_sha == head_sha,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    review = Review(
        repo_name=repo_name,
        pr_number=pr_number,
        pr_title=title,
        pr_url=html_url,
        pr_author=author,
        head_sha=head_sha,
        status=ReviewStatus.QUEUED.value,
        source="github",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def _review_from_diff(payload: ReviewCreateRequest, db: Session) -> Review:
    """Queue a review for a diff pasted into the app (no GitHub involved)."""
    diff_text = (payload.diff or "").strip()
    if "@@" not in diff_text:
        raise HTTPException(
            status_code=422,
            detail="That does not look like a unified diff - it should contain @@ hunk headers.",
        )

    # A bare hunk (no file header) needs a filename to become a valid diff.
    if "diff --git" not in diff_text and not diff_text.startswith("--- "):
        path = (payload.file_path or "pasted.diff").strip().lstrip("/") or "pasted.diff"
        diff_text = build_diff_text(
            [{"path": path, "patch": diff_text, "status": "modified"}]
        )

    parsed = parse_unified_diff(diff_text)
    if not parsed:
        raise HTTPException(
            status_code=422,
            detail="The diff could not be parsed. Check that every hunk starts with @@.",
        )

    review = Review(
        repo_name=PASTED_DIFF_REPO,
        pr_number=0,
        pr_title=(payload.title or "Pasted diff").strip()[:512],
        head_sha=uuid.uuid4().hex,
        status=ReviewStatus.QUEUED.value,
        source="diff",
        diff_text=diff_text,
        files_changed=len(parsed),
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def _review_from_code(payload: ReviewCreateRequest, db: Session) -> Review:
    """Queue a review for a single pasted file.

    The file is converted into a diff where every line is an addition. That is
    honest ("we are reviewing this as new code") and, more importantly, it means
    the whole file is commentable: every finding can be anchored to a line.
    """
    code = payload.code or ""
    if not code.strip():
        raise HTTPException(
            status_code=422,
            detail="There is no code to review.",
        )

    path = (payload.file_path or "pasted.py").strip().lstrip("/") or "pasted.py"
    lines = code.splitlines() or [""]
    patch = f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines)
    diff_text = build_diff_text([{"path": path, "patch": patch, "status": "added"}])

    review = Review(
        repo_name=PASTED_CODE_REPO,
        pr_number=0,
        pr_title=(payload.title or f"Pasted file: {path}").strip()[:512],
        head_sha=uuid.uuid4().hex,
        status=ReviewStatus.QUEUED.value,
        source="code",
        diff_text=diff_text,
        files_changed=1,
        additions=len(lines),
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def _review_from_files(payload: ReviewCreateRequest, db: Session) -> Review:
    """Queue a review for several pasted files at once (mini-project mode).

    Each file becomes an "added file" in one combined diff, so a single AI pass
    sees them together and can catch cross-file problems (a caller passing the
    wrong argument to a function defined in another file, for example).
    """
    files = [item for item in (payload.files or []) if (item.code or "").strip()]
    if not files:
        raise HTTPException(status_code=422, detail="Add at least one file with code.")

    entries = []
    additions = 0
    for item in files:
        path = (item.path or "").strip().lstrip("/")
        if not path:
            raise HTTPException(status_code=422, detail="Every file needs a path.")
        lines = item.code.splitlines() or [""]
        additions += len(lines)
        patch = f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines)
        entries.append({"path": path, "patch": patch, "status": "added"})

    diff_text = build_diff_text(entries)
    review = Review(
        repo_name=PASTED_FILES_REPO,
        pr_number=0,
        pr_title=(payload.title or f"{len(files)} pasted files").strip()[:512],
        head_sha=uuid.uuid4().hex,
        status=ReviewStatus.QUEUED.value,
        source="files",
        diff_text=diff_text,
        files_changed=len(files),
        additions=additions,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@router.get("/{review_id}/metrics", summary="Complexity and size metrics")
def get_review_metrics(review_id: int, db: Session = Depends(get_db)) -> dict:
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")

    return analyse_metrics(added_code_by_file(review.diff_text))


@router.post(
    "/{review_id}/tests",
    response_model=TestsOut,
    summary="Generate a pytest file for this review",
)
def generate_review_tests(review_id: int, db: Session = Depends(get_db)) -> TestsOut:
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")

    code_by_file = added_code_by_file(review.diff_text)
    python_files = {path: code for path, code in code_by_file.items() if path.endswith(".py")}
    if not python_files:
        raise HTTPException(
            status_code=422, detail="Test generation currently supports Python files."
        )

    effective = get_effective_settings(db)
    if not effective.openai_api_key:
        raise HTTPException(
            status_code=400,
            detail="The review engine key is not configured, so tests cannot be generated.",
        )

    try:
        tests = generate_tests(
            api_key=effective.openai_api_key,
            model=effective.openai_model,
            base_url=effective.openai_base_url or None,
            code_by_file=python_files,
            findings=build_findings_payload(review.findings),
            title=review.pr_title,
            timeout=settings.openai_timeout_seconds,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    review.generated_tests = tests
    review.tests_generated_at = datetime.now(timezone.utc)
    db.commit()

    return TestsOut(
        tests=tests, model=effective.openai_model, created_at=review.tests_generated_at
    )

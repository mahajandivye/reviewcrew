"""POST /webhook/github - the entry point for GitHub events.

FULL FLOW (worth understanding before a demo):

  1. You open/update a Pull Request on GitHub.
  2. GitHub POSTs a `pull_request` event to this URL, signed with your secret.
  3. We verify the signature over the RAW body, then insert a `queued` Review.
  4. We hand the Review id to Celery through Redis (`.delay()` == "push a job").
  5. We answer 202 Accepted *immediately*. GitHub rejects responses slower
     than ~10 seconds and will retry; a review takes 20-60 seconds, so it must
     never run inside this request.
  6. A worker picks the job up and does the slow work (Phase 1 task).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.logging_config import get_logger
from app.models import Review, ReviewStatus
from app.schemas import WebhookAck
from app.security import WebhookVerificationError, parse_payload, verify_signature
from app.tasks.review_task import enqueue_review

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhooks"])

# GIT CONCEPT: these are the PR lifecycle events worth reviewing.
#   opened             -> a new PR was created
#   reopened           -> a closed PR was opened again
#   synchronize        -> new commits were pushed to the PR branch
#   ready_for_review   -> a draft PR was marked ready
# "edited", "labeled", "closed" etc. are ignored on purpose.
REVIEWABLE_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}

SIGNATURE_HEADER = "X-Hub-Signature-256"


@router.post(
    "/github",
    response_model=WebhookAck,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive GitHub pull_request webhooks",
)
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(default=None, alias=SIGNATURE_HEADER),
) -> WebhookAck:
    # IMPORTANT: read the raw bytes BEFORE parsing JSON. The HMAC is computed
    # over the exact bytes GitHub sent; re-serialising parsed JSON changes
    # whitespace/key order and the signature will never match.
    raw_body = await request.body()

    if not settings.github_webhook_secret:
        # Fail closed with a 500: this is a server misconfiguration, and
        # silently accepting unsigned events would be a security hole.
        logger.error("Rejecting webhook: GITHUB_WEBHOOK_SECRET is not set")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook secret is not configured on the server.",
        )

    if not verify_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Hub-Signature-256.",
        )

    try:
        payload = parse_payload(raw_body)
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # GitHub sends a `ping` event when you first add the webhook: reply 200-ish
    # so the "Recent Deliveries" tab turns green and you know the URL works.
    if x_github_event == "ping":
        logger.info("Webhook ping received (delivery=%s)", x_github_delivery)
        return WebhookAck(status="pong", detail="Webhook configured correctly.")

    if x_github_event != "pull_request":
        return WebhookAck(status="ignored", detail=f"Unsupported event: {x_github_event!r}")

    action = str(payload.get("action") or "")
    if action not in REVIEWABLE_ACTIONS:
        return WebhookAck(status="ignored", detail=f"Ignored action: {action!r}")

    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}
    repo_full_name = str(repo.get("full_name") or "")
    pr_number = pr.get("number")

    if not repo_full_name or not isinstance(pr_number, int):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload is missing repository.full_name or pull_request.number.",
        )

    # Draft PRs are work in progress; reviewing them is noise.
    if pr.get("draft") is True:
        return WebhookAck(status="ignored", detail="Draft pull request.")
    if str(pr.get("state") or "open") != "open":
        return WebhookAck(status="ignored", detail=f"PR state is {pr.get('state')!r}.")

    head = pr.get("head") or {}
    head_sha = str(head.get("sha") or "")
    if not head_sha:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload is missing pull_request.head.sha.",
        )

    # GIT CONCEPT: each push creates a NEW commit SHA on the PR branch.
    # Reviewing per-SHA (not per-PR) means a later push gets a fresh review,
    # while GitHub's webhook retries for the same SHA do not duplicate work.
    existing = db.execute(
        select(Review).where(
            Review.repo_name == repo_full_name,
            Review.pr_number == pr_number,
            Review.head_sha == head_sha,
        )
    ).scalar_one_or_none()

    if existing is not None:
        logger.info(
            "Review for %s#%s @ %s already exists (id=%s) - skipping duplicate delivery",
            repo_full_name,
            pr_number,
            head_sha[:8],
            existing.id,
        )
        return WebhookAck(
            status="duplicate",
            detail="This commit has already been reviewed.",
            review_id=existing.id,
        )

    review = Review(
        repo_name=repo_full_name,
        pr_number=pr_number,
        pr_title=str(pr.get("title") or ""),
        pr_url=str(pr.get("html_url") or "") or None,
        pr_author=(pr.get("user") or {}).get("login"),
        head_sha=head_sha,
        status=ReviewStatus.QUEUED.value,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    logger.info(
        "Queued review id=%s for %s#%s @ %s (action=%s, delivery=%s)",
        review.id,
        repo_full_name,
        pr_number,
        head_sha[:8],
        action,
        x_github_delivery,
    )

    # --- hand off to Celery ------------------------------------------------ #
    try:
        enqueue_review(review.id)
    except Exception as exc:  # noqa: BLE001 - broker down, Redis down, etc.
        logger.exception("Could not enqueue review %s", review.id)
        review.status = ReviewStatus.FAILED.value
        review.error_message = f"Could not queue the job: {exc}"[:2000]
        review.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Review queued but the worker queue is unavailable. Is Redis running?",
        ) from exc

    return WebhookAck(
        status="queued",
        detail="Review job accepted.",
        review_id=review.id,
    )

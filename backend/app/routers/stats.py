"""GET /api/stats - the four numbers on the dashboard home page.

Implemented with aggregate SQL (COUNT/AVG/GROUP BY) rather than loading rows
into Python: it stays fast as the table grows, and it is the query a reviewer
would expect to see.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Finding, Review, ReviewStatus
from app.schemas import StatsResponse

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=StatsResponse, summary="Dashboard statistics")
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    total_reviews = db.scalar(select(func.count()).select_from(Review)) or 0

    status_rows = db.execute(
        select(Review.status, func.count()).group_by(Review.status)
    ).all()
    by_status = {status: int(count) for status, count in status_rows}

    issues_found = db.scalar(select(func.count()).select_from(Finding)) or 0

    severity_rows = db.execute(
        select(Finding.severity, func.count()).group_by(Finding.severity)
    ).all()
    by_severity = {str(sev): int(count) for sev, count in severity_rows}

    category_rows = db.execute(
        select(Finding.category, func.count()).group_by(Finding.category)
    ).all()
    by_category = {str(cat): int(count) for cat, count in category_rows}

    # AVG over an integer column returns a Decimal in Postgres; cast for JSON.
    avg_ms = db.scalar(
        select(func.avg(Review.duration_ms)).where(Review.duration_ms.isnot(None))
    )
    avg_seconds = round(float(avg_ms) / 1000.0, 2) if avg_ms is not None else 0.0

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    last_7_days = (
        db.scalar(
            select(func.count()).select_from(Review).where(Review.created_at >= week_ago)
        )
        or 0
    )

    return StatsResponse(
        total_reviews=int(total_reviews),
        reviews_in_progress=by_status.get(ReviewStatus.QUEUED.value, 0)
        + by_status.get(ReviewStatus.RUNNING.value, 0),
        completed_reviews=by_status.get(ReviewStatus.COMPLETED.value, 0),
        failed_reviews=by_status.get(ReviewStatus.FAILED.value, 0),
        issues_found=int(issues_found),
        high_severity_count=by_severity.get("high", 0),
        avg_review_seconds=avg_seconds,
        reviews_last_7_days=int(last_7_days),
        findings_by_severity=by_severity,
        findings_by_category=by_category,
    )

"""API tests: reviews list/detail, stats, settings validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Finding, Review, ReviewStatus


def _make_review(db, *, pr=1, repo="acme/shop", status="completed", duration_ms=4200):
    now = datetime.now(timezone.utc)
    review = Review(
        repo_name=repo,
        pr_number=pr,
        pr_title=f"Add checkout flow #{pr}",
        head_sha=f"sha{pr}" * 10,
        status=status,
        files_changed=2,
        additions=10,
        deletions=3,
        duration_ms=duration_ms,
        created_at=now,
        completed_at=now if status == "completed" else None,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def _make_finding(db, review, *, severity="medium", category="bug", line=10, message="Issue"):
    finding = Finding(
        review_id=review.id,
        file_path="app/main.py",
        line_number=line,
        severity=severity,
        category=category,
        message=message,
        suggestion="Fix it",
        source="ai",
    )
    db.add(finding)
    db.commit()
    return finding


def test_list_reviews_is_paginated(client, db):
    for pr in range(1, 4):
        _make_review(db, pr=pr)

    response = client.get("/api/reviews", params={"page": 1, "page_size": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 2

    page_two = client.get("/api/reviews", params={"page": 2, "page_size": 2}).json()
    assert len(page_two["items"]) == 1


def test_list_reviews_includes_finding_counts(client, db):
    review = _make_review(db)
    _make_finding(db, review, severity="high", line=1)
    _make_finding(db, review, severity="high", line=2)
    _make_finding(db, review, severity="low", line=3)

    item = client.get("/api/reviews").json()["items"][0]
    assert item["findings_count"] == 3
    assert item["high_severity_count"] == 2
    assert item["duration_seconds"] == 4.2


def test_list_reviews_filters_by_status(client, db):
    _make_review(db, pr=1, status="completed")
    _make_review(db, pr=2, status="failed")

    body = client.get("/api/reviews", params={"status": "failed"}).json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "failed"


def test_list_reviews_rejects_bad_status(client):
    response = client.get("/api/reviews", params={"status": "exploded"})
    assert response.status_code == 422


def test_list_reviews_rejects_bad_page_size(client):
    assert client.get("/api/reviews", params={"page_size": 0}).status_code == 422
    assert client.get("/api/reviews", params={"page_size": 500}).status_code == 422


def test_review_detail_orders_findings_by_severity(client, db):
    review = _make_review(db)
    _make_finding(db, review, severity="low", line=30, message="low")
    _make_finding(db, review, severity="high", line=10, message="high")
    _make_finding(db, review, severity="medium", line=20, message="medium")

    response = client.get(f"/api/reviews/{review.id}")
    assert response.status_code == 200
    body = response.json()

    assert [f["severity"] for f in body["findings"]] == ["high", "medium", "low"]
    assert body["counts_by_severity"] == {"high": 1, "medium": 1, "low": 1}


def test_review_detail_404(client):
    assert client.get("/api/reviews/9999").status_code == 404


def test_stats_aggregates(client, db):
    review_a = _make_review(db, pr=1, duration_ms=2000)
    review_b = _make_review(db, pr=2, duration_ms=4000)
    _make_finding(db, review_a, severity="high")
    _make_finding(db, review_a, severity="medium")
    _make_finding(db, review_b, severity="low")

    body = client.get("/api/stats").json()
    assert body["total_reviews"] == 2
    assert body["completed_reviews"] == 2
    assert body["issues_found"] == 3
    assert body["high_severity_count"] == 1
    assert body["avg_review_seconds"] == 3.0


def test_stats_on_empty_database(client):
    body = client.get("/api/stats").json()
    assert body["total_reviews"] == 0
    assert body["avg_review_seconds"] == 0.0


def test_settings_masks_secrets(client):
    response = client.patch(
        "/api/settings",
        json={"openai_api_key": "sk-proj-abcdefghijklmnop1234", "openai_model": "gpt-4o-mini"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["openai_api_key_configured"] is True
    # The full key must never come back over the wire.
    assert "abcdefghijklmnop" not in body["openai_api_key"]
    assert body["openai_api_key"].startswith("sk-p")


def test_settings_partial_update_keeps_other_values(client):
    client.patch("/api/settings", json={"openai_model": "gpt-4o"})
    client.patch("/api/settings", json={"post_pr_comments": False})

    body = client.get("/api/settings").json()
    assert body["openai_model"] == "gpt-4o"
    assert body["post_pr_comments"] is False


def test_retry_failed_review(client, db, monkeypatch):
    review = _make_review(db, status=ReviewStatus.FAILED.value)
    _make_finding(db, review, message="stale")

    import app.routers.reviews as reviews_router

    monkeypatch.setattr(reviews_router, "enqueue_review", lambda review_id: "task-1")

    response = client.post(f"/api/reviews/{review.id}/retry")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"

    db.expire_all()
    refreshed = db.get(Review, review.id)
    assert refreshed.status == "queued"
    # Stale findings are cleared so a retry cannot mix old and new results.
    assert refreshed.findings == []


def test_retry_conflicts_when_already_running(client, db):
    review = _make_review(db, status="running")
    assert client.post(f"/api/reviews/{review.id}/retry").status_code == 409


DIFF = """diff --git a/app/x.py b/app/x.py
--- a/app/x.py
+++ b/app/x.py
@@ -1,3 +1,4 @@
 import os
-old = 1
+new = 1
+extra = 2
"""


def test_diff_endpoint_returns_structured_hunks(client, db):
    review = _make_review(db)
    review.diff_text = DIFF
    db.commit()

    response = client.get(f"/api/reviews/{review.id}/diff")
    assert response.status_code == 200
    body = response.json()

    assert body["has_diff"] is True
    file_diff = body["files"][0]
    assert file_diff["path"] == "app/x.py"
    assert file_diff["status"] == "modified"
    assert file_diff["language"] == "Python"
    assert file_diff["additions"] == 2
    assert file_diff["deletions"] == 1

    lines = file_diff["hunks"][0]["lines"]
    kinds = [line["kind"] for line in lines]
    assert kinds == ["context", "del", "add", "add"]
    # The viewer annotates added lines by new_line, so it must be exact.
    assert lines[2]["new_line"] == 2
    assert lines[3]["new_line"] == 3
    assert lines[1]["old_line"] == 2


def test_diff_endpoint_without_stored_diff(client, db):
    review = _make_review(db)  # seeded with diff_text=""
    body = client.get(f"/api/reviews/{review.id}/diff").json()
    assert body["has_diff"] is False
    assert body["files"] == []


def test_diff_endpoint_404(client):
    assert client.get("/api/reviews/9999/diff").status_code == 404

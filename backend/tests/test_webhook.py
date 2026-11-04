"""Webhook tests: HMAC verification, event filtering, idempotency.

These are the security-critical tests. If signature verification regresses,
anyone on the internet can burn your OpenAI credits.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.models import Review

SECRET = "test-webhook-secret"


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def pr_payload(*, action="opened", draft=False, sha="abc123def456", number=7):
    return {
        "action": action,
        "number": number,
        "pull_request": {
            "number": number,
            "title": "Add coupon support",
            "html_url": f"https://github.com/acme/shop/pull/{number}",
            "state": "open",
            "draft": draft,
            "user": {"login": "octocat"},
            "head": {"sha": sha},
        },
        "repository": {"full_name": "acme/shop"},
    }


def post_webhook(client, payload, *, headers=None, secret=SECRET):
    body = json.dumps(payload).encode()
    default_headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "delivery-1",
        "X-Hub-Signature-256": sign(body, secret),
    }
    return client.post("/webhook/github", content=body, headers={**default_headers, **(headers or {})})


@pytest.fixture()
def captured_jobs(monkeypatch):
    """Replace Celery's .delay with a list append (no Redis in tests)."""
    jobs: list[int] = []
    import app.routers.webhooks as webhooks

    monkeypatch.setattr(webhooks, "enqueue_review", lambda review_id: jobs.append(review_id))
    return jobs


def test_missing_signature_is_rejected(client, captured_jobs):
    body = json.dumps(pr_payload()).encode()
    response = client.post(
        "/webhook/github",
        content=body,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "pull_request"},
    )
    assert response.status_code == 401
    assert captured_jobs == []


def test_wrong_signature_is_rejected(client, captured_jobs):
    response = post_webhook(client, pr_payload(), secret="the-wrong-secret")
    assert response.status_code == 401
    assert captured_jobs == []


def test_tampered_body_is_rejected(client, captured_jobs):
    payload = pr_payload()
    body = json.dumps(payload).encode()
    signature = sign(body)  # signature for the ORIGINAL body
    tampered = json.dumps({**payload, "action": "synchronize"}).encode()

    response = client.post(
        "/webhook/github",
        content=tampered,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": signature,
        },
    )
    assert response.status_code == 401


def test_ping_event_is_acknowledged(client):
    body = json.dumps({"zen": "Keep it logically awesome."}).encode()
    response = client.post(
        "/webhook/github",
        content=body,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "ping", "X-Hub-Signature-256": sign(body)},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pong"


def test_non_pull_request_event_is_ignored(client, captured_jobs):
    response = post_webhook(client, {"action": "created"}, headers={"X-GitHub-Event": "issue_comment"})
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
    assert captured_jobs == []


def test_unhandled_action_is_ignored(client, captured_jobs):
    response = post_webhook(client, pr_payload(action="closed"))
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
    assert captured_jobs == []


def test_draft_pr_is_ignored(client, captured_jobs):
    response = post_webhook(client, pr_payload(draft=True))
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"


def test_opened_pr_creates_review_and_queues_job(client, db, captured_jobs):
    response = post_webhook(client, pr_payload())
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"

    review = db.get(Review, body["review_id"])
    assert review is not None
    assert review.repo_name == "acme/shop"
    assert review.pr_number == 7
    assert review.status == "queued"
    assert review.head_sha == "abc123def456"
    assert captured_jobs == [review.id]


def test_duplicate_delivery_is_idempotent(client, db, captured_jobs):
    first = post_webhook(client, pr_payload())
    second = post_webhook(client, pr_payload())

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["status"] == "duplicate"
    assert second.json()["review_id"] == first.json()["review_id"]
    # Only one job was queued, so no double OpenAI spend.
    assert len(captured_jobs) == 1


def test_new_commit_on_same_pr_creates_new_review(client, db, captured_jobs):
    post_webhook(client, pr_payload(sha="aaa111"))
    post_webhook(client, pr_payload(action="synchronize", sha="bbb222"))

    assert len(captured_jobs) == 2
    assert db.query(Review).count() == 2


def test_broker_failure_marks_review_failed(client, db, monkeypatch):
    import app.routers.webhooks as webhooks

    def boom(review_id):
        raise RuntimeError("redis is down")

    monkeypatch.setattr(webhooks, "enqueue_review", boom)

    response = post_webhook(client, pr_payload())
    assert response.status_code == 503

    review = db.query(Review).one()
    assert review.status == "failed"
    assert "redis is down" in (review.error_message or "")

"""Tests for the self-serve review flow and the chat endpoint.

These cover the behaviours that make ReviewPilot a platform rather than a bot:
creating a review from pasted code, from a pasted diff, and from a PR URL.
"""

from __future__ import annotations

import pytest

from app.models import Review


@pytest.fixture()
def queued(monkeypatch):
    """Capture enqueue calls instead of hitting Redis."""
    jobs: list[int] = []
    import app.routers.reviews as reviews_router

    monkeypatch.setattr(reviews_router, "enqueue_review", lambda review_id: jobs.append(review_id))
    return jobs


def test_create_review_from_pasted_code(client, db, queued):
    code = "import os\n\n\ndef total(items):\n    return sum(items) + undefined\n"
    response = client.post(
        "/api/reviews",
        json={"source": "code", "file_path": "cart.py", "code": code, "title": "Cart module"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "code"
    assert body["status"] == "queued"
    assert body["pr_title"] == "Cart module"

    review = db.get(Review, body["id"])
    assert review is not None
    # Every line of the pasted file becomes an addition -> all lines reviewable
    assert review.diff_text.startswith("diff --git a/cart.py b/cart.py")
    assert "+    return sum(items) + undefined" in review.diff_text
    assert queued == [review.id]


def test_create_review_from_pasted_code_rejects_empty(client, queued):
    response = client.post("/api/reviews", json={"source": "code", "code": "   "})
    assert response.status_code == 422


def test_create_review_from_pasted_diff(client, db, queued):
    diff = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,3 @@\n"
        " import os\n"
        "+SECRET = 'sk-proj-abcdefghijklmnop1234567890'\n"
    )
    response = client.post("/api/reviews", json={"source": "diff", "diff": diff})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "diff"

    review = db.get(Review, body["id"])
    assert review.head_sha  # synthetic id, keeps the unique constraint happy
    assert queued == [review.id]


def test_create_review_from_bare_hunk_is_wrapped(client, db, queued):
    # A hunk without file headers is a common copy-paste; it must still work.
    diff = "@@ -1,2 +1,2 @@\n-old = 1\n+new = 2\n"
    response = client.post(
        "/api/reviews",
        json={"source": "diff", "diff": diff, "file_path": "app/config.py"},
    )
    assert response.status_code == 201, response.text
    review = db.get(Review, response.json()["id"])
    assert "app/config.py" in review.diff_text


def test_create_review_rejects_non_diff(client, queued):
    response = client.post("/api/reviews", json={"source": "diff", "diff": "hello world"})
    assert response.status_code == 422



def test_pr_url_without_token_fetches_public_pr(client, db, queued, monkeypatch):
    """No GitHub token: public PRs are read anonymously and reviewed."""
    import app.routers.reviews as reviews_router
    from types import SimpleNamespace

    fake_pr = SimpleNamespace(
        head=SimpleNamespace(sha="abc123def456"),
        title="Fix a bug in the parser",
        user=SimpleNamespace(login="octocat"),
        html_url="https://github.com/acme/shop/pull/12",
    )

    class FakeClient:
        def __init__(self, token):
            assert token == ""

        def get_pull_request(self, repo, number):
            assert repo == "acme/shop"
            assert number == 12
            return fake_pr

    monkeypatch.setattr(reviews_router, "GitHubClient", FakeClient)
    monkeypatch.setattr(
        reviews_router,
        "get_effective_settings",
        lambda db: type("S", (), {"github_token": ""})(),
    )

    response = client.post(
        "/api/reviews",
        json={"source": "pr", "pr_url": "https://github.com/acme/shop/pull/12"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "github"
    assert body["pr_title"] == "Fix a bug in the parser"
    assert queued == [body["id"]]


def test_pr_url_github_failure_is_reported(client, queued, monkeypatch):
    import app.routers.reviews as reviews_router
    from app.services.github_service import GitHubError

    class FailingClient:
        def __init__(self, token):
            pass

        def get_pull_request(self, repo, number):
            raise GitHubError("404 Not Found")

    monkeypatch.setattr(reviews_router, "GitHubClient", FailingClient)
    monkeypatch.setattr(
        reviews_router,
        "get_effective_settings",
        lambda db: type("S", (), {"github_token": ""})(),
    )

    response = client.post(
        "/api/reviews",
        json={"source": "pr", "pr_url": "https://github.com/acme/private/pull/1"},
    )
    assert response.status_code == 400
    assert "could not load" in response.json()["detail"].lower()



def test_create_review_rejects_bad_pr_url(client, queued):
    response = client.post(
        "/api/reviews", json={"source": "pr", "pr_url": "https://example.com/not/a/pr"}
    )
    assert response.status_code == 422


def test_chat_requires_openrouter_key(client, monkeypatch):
    # Force the "no key" branch even when the machine's .env has a real key.
    import app.routers.chat as chat_router
    from app.services.settings_service import EffectiveSettings

    monkeypatch.setattr(
        chat_router,
        "get_effective_settings",
        lambda db: EffectiveSettings(
            github_token="",
            openai_api_key="",
            openai_model="gpt-4o-mini",
            openrouter_api_key="",
            chat_model="openai/gpt-4o-mini",
            post_pr_comments=False,
        ),
    )

    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 400
    assert "openrouter" in response.json()["detail"].lower()


def test_settings_expose_chat_model(client):
    response = client.patch(
        "/api/settings",
        json={"chat_model": "anthropic/claude-3.5-sonnet", "openrouter_api_key": "sk-or-v1-test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["chat_model"] == "anthropic/claude-3.5-sonnet"
    assert body["openrouter_api_key_configured"] is True
    assert "sk-or-v1-test" not in body["openrouter_api_key"]

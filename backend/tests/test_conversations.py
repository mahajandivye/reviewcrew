"""Tests for saved conversations (chat history) and deletion."""

from __future__ import annotations

from app.models import Review


def test_create_and_fetch_conversation(client):
    created = client.post("/api/conversations", json={})
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["title"] == "New chat"
    assert conversation["messages"] == []

    fetched = client.get(f"/api/conversations/{conversation['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == conversation["id"]


def test_first_user_message_becomes_the_title(client):
    conversation = client.post("/api/conversations", json={}).json()
    response = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"role": "user", "kind": "text", "content": "Why is this SQL injection a problem?"},
    )
    assert response.status_code == 201
    assert response.json()["content"] == "Why is this SQL injection a problem?"

    detail = client.get(f"/api/conversations/{conversation['id']}").json()
    assert detail["title"] == "Why is this SQL injection a problem?"
    assert detail["message_count"] == 1


def test_messages_append_in_order(client):
    conversation = client.post("/api/conversations", json={}).json()
    first = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"role": "user", "kind": "text", "content": "first"},
    )
    second = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"role": "assistant", "kind": "text", "content": "second"},
    )
    assert first.status_code == 201
    assert second.status_code == 201

    detail = client.get(f"/api/conversations/{conversation['id']}").json()
    assert [m["content"] for m in detail["messages"]] == ["first", "second"]


def test_review_message_links_to_review(client, db):
    review = Review(
        repo_name="pasted/code",
        pr_number=0,
        pr_title="Pasted file: app/db.py",
        head_sha="abc123",
        status="completed",
        source="code",
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    conversation = client.post("/api/conversations", json={}).json()
    response = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"role": "assistant", "kind": "review", "review_id": review.id},
    )
    assert response.status_code == 201
    assert response.json()["review_id"] == review.id

    # The review title names a chat whose first message is a review card.
    assert client.get(f"/api/conversations/{conversation['id']}").json()["title"] == (
        "Pasted file: app/db.py"
    )


def test_review_message_with_missing_review_is_rejected(client):
    conversation = client.post("/api/conversations", json={}).json()
    response = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"role": "assistant", "kind": "review", "review_id": 9999},
    )
    assert response.status_code == 404


def test_list_is_ordered_by_recent_activity(client):
    first = client.post("/api/conversations", json={"title": "older"}).json()
    second = client.post("/api/conversations", json={"title": "newer"}).json()

    # Touch the first one so it becomes the most recent.
    client.post(
        f"/api/conversations/{first['id']}/messages",
        json={"role": "user", "kind": "text", "content": "bump"},
    )

    items = client.get("/api/conversations").json()
    assert [item["title"] for item in items] == ["older", "newer"]
    assert items[0]["preview"] == "bump"
    assert second["id"] != first["id"]


def test_rename_conversation(client):
    conversation = client.post("/api/conversations", json={"title": "old"}).json()
    response = client.patch(
        f"/api/conversations/{conversation['id']}", json={"title": "checkout review"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "checkout review"


def test_delete_conversation(client):
    conversation = client.post("/api/conversations", json={}).json()
    response = client.delete(f"/api/conversations/{conversation['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/conversations/{conversation['id']}").status_code == 404


def test_delete_missing_conversation_404(client):
    assert client.delete("/api/conversations/9999").status_code == 404


def test_append_to_missing_conversation_404(client):
    response = client.post(
        "/api/conversations/9999/messages",
        json={"role": "user", "kind": "text", "content": "hi"},
    )
    assert response.status_code == 404

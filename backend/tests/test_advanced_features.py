"""Tests for metrics, custom rules, multi-file input and test generation."""

from __future__ import annotations

from app.models import Review
from app.services.metrics import analyse, analyse_file
from app.services.rules_service import apply_rules


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def test_metrics_count_functions_and_complexity():
    code = (
        "def total(items):\n"
        "    if not items:\n"
        "        return 0\n"
        "    return sum(items)\n"
    )
    result = analyse_file("app/math.py", code)
    assert result["language"] == "Python"
    assert result["functions"] == 1
    assert result["code_lines"] == 4
    assert result["max_complexity"] >= 2
    assert result["maintainability"] is not None
    assert result["grade"] in {"A", "B", "C", "D", "F"}


def test_metrics_are_aggregated_across_files():
    result = analyse(
        {
            "a.py": "def a():\n    return 1\n",
            "b.py": "def b():\n    if True:\n        return 2\n",
        }
    )
    assert result["available"] is True
    assert result["totals"]["files"] == 2
    assert result["totals"]["functions"] == 2
    assert result["maintainability"]["grade"] in {"A", "B", "C"}
    assert len(result["files"]) == 2


def test_non_python_gets_counts_but_no_complexity():
    result = analyse_file("web/app.js", "function a() {\n  return 1;\n}\n")
    assert result["language"] == "JavaScript"
    assert result["code_lines"] == 3
    assert result["average_complexity"] is None
    assert "Python-only" in (result["error"] or "")


def test_empty_metrics_are_reported_as_unavailable():
    assert analyse({})["available"] is False


# --------------------------------------------------------------------------- #
# Custom rules
# --------------------------------------------------------------------------- #
def test_rules_roundtrip(client):
    payload = {
        "rules": [
            {
                "name": "No print in production",
                "pattern": r"\bprint\(",
                "message": "Do not ship print() calls.",
                "severity": "medium",
                "category": "style",
                "enabled": True,
            }
        ]
    }
    saved = client.put("/api/rules", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()[0]["name"] == "No print in production"

    listed = client.get("/api/rules")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_rules_reject_invalid_regex(client):
    response = client.put(
        "/api/rules",
        json={"rules": [{"name": "broken", "pattern": "([", "message": "x"}]},
    )
    assert response.status_code == 422
    assert "invalid regex" in response.json()["detail"].lower()


def test_rule_matches_added_lines():
    rules = [
        {
            "name": "No eval",
            "pattern": r"\beval\(",
            "message": "eval is dangerous",
            "severity": "high",
            "category": "security",
            "enabled": True,
        }
    ]
    drafts = apply_rules("app/x.py", {3: "result = eval(user_input)"}, rules)
    assert len(drafts) == 1
    assert drafts[0].severity == "high"
    assert drafts[0].line_number == 3
    assert drafts[0].source == "rule"


def test_disabled_rule_does_not_match():
    rules = [
        {"name": "x", "pattern": "print", "message": "m", "severity": "low",
         "category": "style", "enabled": False}
    ]
    assert apply_rules("app/x.py", {1: "print('hi')"}, rules) == []


# --------------------------------------------------------------------------- #
# Multi-file review
# --------------------------------------------------------------------------- #
def test_create_review_from_multiple_files(client, db, monkeypatch):
    import app.routers.reviews as reviews_router

    jobs = []
    monkeypatch.setattr(reviews_router, "enqueue_review", lambda review_id: jobs.append(review_id))

    response = client.post(
        "/api/reviews",
        json={
            "source": "files",
            "title": "Mini project",
            "files": [
                {"path": "app/models.py", "code": "def load(id):\n    return id\n"},
                {"path": "app/routes.py", "code": "from app.models import load\n\nload('x', 2)\n"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    review = db.get(Review, body["id"])
    assert review.source == "files"
    assert review.files_changed == 2
    assert "app/models.py" in review.diff_text
    assert "app/routes.py" in review.diff_text
    assert jobs == [review.id]


def test_files_source_requires_content(client):
    response = client.post("/api/reviews", json={"source": "files", "files": []})
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Metrics + tests endpoints
# --------------------------------------------------------------------------- #
def test_metrics_endpoint_uses_stored_code(client, db):
    review = Review(
        repo_name="pasted/code", pr_number=0, pr_title="p", head_sha="sha1",
        status="completed", source="code",
        diff_text=(
            "diff --git a/app/x.py b/app/x.py\n"
            "new file mode 100644\n--- /dev/null\n+++ b/app/x.py\n"
            "@@ -0,0 +1,3 @@\n+def f():\n+    if True:\n+        return 1\n"
        ),
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    body = client.get(f"/api/reviews/{review.id}/metrics").json()
    assert body["available"] is True
    assert body["totals"]["functions"] == 1
    assert body["complexity"]["max"] >= 2


def test_metrics_endpoint_404(client):
    assert client.get("/api/reviews/9999/metrics").status_code == 404


def test_generate_tests_rejects_non_python(client, db):
    review = Review(
        repo_name="pasted/code", pr_number=0, pr_title="p", head_sha="sha2",
        status="completed", source="code",
        diff_text=(
            "diff --git a/web/app.js b/web/app.js\n"
            "new file mode 100644\n--- /dev/null\n+++ b/web/app.js\n"
            "@@ -0,0 +1,2 @@\n+function a() {\n+}\n"
        ),
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    response = client.post(f"/api/reviews/{review.id}/tests")
    assert response.status_code == 422
    assert "python" in response.json()["detail"].lower()

"""Chat context must include the reviewed code, not just the findings."""

from __future__ import annotations

from app.models import Review
from app.routers.chat import _review_context


def _pasted_review(db, source="code", diff_text=""):
    review = Review(
        repo_name="pasted/code",
        pr_number=0,
        pr_title="Pasted file: app/db.py",
        head_sha="abc123",
        status="completed",
        source=source,
        diff_text=diff_text,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def test_context_contains_the_pasted_code(db):
    diff = (
        "diff --git a/app/db.py b/app/db.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/app/db.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+def total(items):\n"
        "+    cache = []\n"
        "+    return sum(items)\n"
    )
    review = _pasted_review(db, diff_text=diff)

    context = _review_context(db, review.id)

    # This is what makes "now optimise this for memory" work.
    assert "Code under review" in context
    assert "def total(items):" in context
    assert "return sum(items)" in context


def test_context_contains_the_pasted_diff(db):
    diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
    review = _pasted_review(db, source="diff", diff_text=diff)

    context = _review_context(db, review.id)

    assert "Code under review" in context
    assert "+x = 2" in context


def test_context_without_code_still_has_metadata(db):
    review = _pasted_review(db, source="github", diff_text="")
    context = _review_context(db, review.id)

    assert "Pasted file: app/db.py" in context
    assert "No findings were reported" in context


def test_context_is_capped(db):
    huge = "diff --git a/a.py b/a.py\n" + "\n".join(f"+line {i}" for i in range(5000))
    review = _pasted_review(db, diff_text=huge)
    context = _review_context(db, review.id)
    assert len(context) <= 9_000

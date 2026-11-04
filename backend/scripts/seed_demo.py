#!/usr/bin/env python
"""Seed the database with realistic demo data.

Why: you want a populated dashboard *before* your first real PR, and the demo
must not depend on GitHub/OpenAI being reachable while a judge is watching.

    cd backend
    python scripts/seed_demo.py

Creates (idempotently) three reviews: one completed with six findings across
three files, one failed (shows the error state), one completed from another repo.
The completed reviews include a real unified diff, so the Phase 4 diff viewer has
something to render.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Conversation, Finding, Review, ReviewStatus  # noqa: E402
from app.services.diff_parser import build_diff_text  # noqa: E402

DEMO_REPO = "acme/demo-shop"

# --------------------------------------------------------------------------- #
# Diffs (hand-written to be valid unified diffs)
# --------------------------------------------------------------------------- #
CHECKOUT_PATCH = """@@ -1,6 +1,8 @@
 from decimal import Decimal

 def apply_discount(total, percent):
-    if percent > 100:
-        percent = 100
-    return total - (total * Decimal(percent) / 100)
+    return total - (total * Decimal(percent) / 100)
+
+
+def charge_card(token, amount):
+    return amount
"""

CART_PATCH = """@@ -6,4 +6,5 @@
 @router.get("/cart/{cart_id}")
 def get_cart(cart_id: int):
     cart = load_cart(cart_id)
-    return cart
+    total = cart.total_price()
+    return {"cart": cart, "total": total, "coupon": coupon_code}
"""

PAYMENTS_PATCH = """@@ -0,0 +1,6 @@
+import stripe
+
+STRIPE_KEY = "demo-placeholder-not-a-real-key"
+
+def charge(amount):
+    return stripe.Charge.create(amount=amount, api_key=STRIPE_KEY)
"""

DOCS_PATCH = """@@ -12,4 +12,5 @@
 ## Installation

 Run the server:
-    uvicorn main:app
+    uvicorn app.main:app --reload
+The dashboard is on port 5173.
"""


def build_checkout_diff() -> str:
    return build_diff_text(
        [
            {"path": "app/services/checkout.py", "patch": CHECKOUT_PATCH},
            {"path": "app/api/cart.py", "patch": CART_PATCH},
            {"path": "app/services/payments.py", "patch": PAYMENTS_PATCH, "status": "added"},
        ]
    )


def build_docs_diff() -> str:
    return build_diff_text([{"path": "docs/setup.md", "patch": DOCS_PATCH}])


def add_review(
    db,
    *,
    repo: str,
    pr_number: int,
    title: str,
    status: str,
    created_at: datetime,
    duration_ms: int | None,
    findings: list[dict],
    diff_text: str = "",
    error_message: str | None = None,
) -> Review:
    review = Review(
        repo_name=repo,
        pr_number=pr_number,
        pr_title=title,
        pr_url=f"https://github.com/{repo}/pull/{pr_number}",
        pr_author="octocat",
        head_sha=f"{pr_number:02d}" + "a1b2c3d4" * 5,
        status=status,
        files_changed=len({f["file_path"] for f in findings}) or 3,
        additions=0,
        deletions=0,
        duration_ms=duration_ms,
        diff_text=diff_text,
        error_message=error_message,
        created_at=created_at,
        started_at=created_at + timedelta(seconds=1) if status != ReviewStatus.QUEUED.value else None,
        completed_at=created_at + timedelta(milliseconds=duration_ms or 0)
        if status in {ReviewStatus.COMPLETED.value, ReviewStatus.FAILED.value}
        else None,
        github_review_url=f"https://github.com/{repo}/pull/{pr_number}#pullrequestreview-1"
        if status == ReviewStatus.COMPLETED.value
        else None,
    )
    db.add(review)
    db.flush()

    for item in findings:
        db.add(
            Finding(
                review_id=review.id,
                file_path=item["file_path"],
                line_number=item["line_number"],
                severity=item["severity"],
                category=item["category"],
                message=item["message"],
                suggestion=item.get("suggestion"),
                source=item.get("source", "ai"),
            )
        )

    # Cheap, honest line counts for the demo (ignore --- / +++ headers).
    additions = deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    review.additions = additions
    review.deletions = deletions
    db.commit()
    return review


DEMO_FINDINGS = [
    {
        "file_path": "app/services/payments.py",
        "line_number": 3,
        "severity": "high",
        "category": "security",
        "message": "Possible hardcoded Stripe secret key: `sk_l...(hidden)...i789`",
        "suggestion": "Revoke this key in the Stripe dashboard, then read it from "
        "`os.environ['STRIPE_SECRET_KEY']`.",
        "source": "secret",
    },
    {
        "file_path": "app/api/cart.py",
        "line_number": 10,
        "severity": "high",
        "category": "bug",
        "message": "undefined name 'coupon_code'",
        "suggestion": "This name is never imported or assigned. Add the import, or "
        "remove the reference.",
        "source": "static",
    },
    {
        "file_path": "app/services/checkout.py",
        "line_number": 4,
        "severity": "medium",
        "category": "bug",
        "message": "The guard that clamped `percent` to 100 was removed, so a coupon "
        "of 150% now produces a negative total instead of being capped.",
        "suggestion": "Restore the clamp before the calculation:\n\n"
        "```python\nif percent > 100:\n    percent = 100\n```",
    },
    {
        "file_path": "app/api/cart.py",
        "line_number": 9,
        "severity": "medium",
        "category": "bug",
        "message": "`cart.total_price()` is called without checking that `load_cart` "
        "returned a cart. A missing cart id raises AttributeError -> HTTP 500 instead "
        "of a 404.",
        "suggestion": "```python\nif cart is None:\n    raise HTTPException(status_code=404, "
        "detail=\"Cart not found\")\n```",
    },
    {
        "file_path": "app/services/checkout.py",
        "line_number": 7,
        "severity": "low",
        "category": "style",
        "message": "`charge_card` accepts a `token` argument but ignores it, which makes "
        "callers believe the payment is authenticated.",
        "suggestion": "Remove the parameter, or pass it through to the payment provider.",
    },
    {
        "file_path": "app/services/payments.py",
        "line_number": 6,
        "severity": "low",
        "category": "style",
        "message": "The Stripe call has no timeout or error handling, so a provider "
        "outage blocks the request until the socket times out.",
        "suggestion": "Wrap it in try/except and set a request timeout.",
    },
]

DOCS_FINDINGS = [
    {
        "file_path": "docs/setup.md",
        "line_number": 15,
        "severity": "low",
        "category": "style",
        "message": "The code block on line 15 is not fenced, so the command renders as "
        "prose in the README view.",
        "suggestion": "Wrap the command in triple backticks.",
    },
]


def add_chats(db) -> int:
    """Create one saved chat per review that does not have one yet."""
    linked = {
        message.get("review_id")
        for conversation in db.query(Conversation).all()
        for message in (conversation.messages or [])
        if message.get("kind") == "review"
    }

    created = 0
    for review in db.query(Review).order_by(Review.created_at).all():
        if review.id in linked:
            continue
        db.add(
            Conversation(
                title=(review.pr_title or f"Review #{review.id}")[:60],
                messages=[
                    {
                        "role": "assistant",
                        "kind": "review",
                        "content": "",
                        "review_id": review.id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            )
        )
        created += 1
    db.commit()
    return created


def main() -> int:
    # create_all is a no-op when Alembic already created the tables, and it
    # saves you when you just want demo data in a fresh SQLite file.
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        # Idempotent: remove previous demo rows for this repo, keep real reviews.
        existing = db.query(Review).filter(Review.repo_name.in_([DEMO_REPO, "octo/docs-site"])).all()
        if existing:
            # Delete children explicitly too: ON DELETE CASCADE only runs when
            # the database enforces foreign keys (SQLite needs a pragma).
            review_ids = [review.id for review in existing]
            db.query(Finding).filter(Finding.review_id.in_(review_ids)).delete(
                synchronize_session=False
            )
            # Chats that pointed at those reviews would dangle.
            dead = set(review_ids)
            for conversation in db.query(Conversation).all():
                if any(
                    message.get("review_id") in dead
                    for message in (conversation.messages or [])
                ):
                    db.delete(conversation)
            for review in existing:
                db.delete(review)
        db.commit()

        now = datetime.now(timezone.utc)

        newest = add_review(
            db,
            repo=DEMO_REPO,
            pr_number=42,
            title="Add coupon support to checkout",
            status=ReviewStatus.COMPLETED.value,
            created_at=now - timedelta(minutes=18),
            duration_ms=8_450,
            findings=DEMO_FINDINGS,
            diff_text=build_checkout_diff(),
        )

        add_review(
            db,
            repo=DEMO_REPO,
            pr_number=38,
            title="Refactor the payment retry loop",
            status=ReviewStatus.FAILED.value,
            created_at=now - timedelta(hours=3),
            duration_ms=1_200,
            findings=[],
            error_message="No GitHub token configured. Set GITHUB_TOKEN in .env or save one "
            "on the Settings page.",
        )

        add_review(
            db,
            repo="octo/docs-site",
            pr_number=12,
            title="Document the new setup steps",
            status=ReviewStatus.COMPLETED.value,
            created_at=now - timedelta(days=1, hours=2),
            duration_ms=12_300,
            findings=DOCS_FINDINGS,
            diff_text=build_docs_diff(),
        )

        # The sidebar lists chats, so give each demo review a matching chat.
        add_chats(db)

        print("Seeded demo data:")
        print(f"  - {DEMO_REPO}#42  completed, 6 findings (id={newest.id})")
        print(f"  - {DEMO_REPO}#38  failed")
        print("  - octo/docs-site#12 completed, 1 finding")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

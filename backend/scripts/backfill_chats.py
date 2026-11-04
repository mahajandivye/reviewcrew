#!/usr/bin/env python
"""Create a chat for every review that does not have one yet.

Why: the sidebar lists saved chats. Reviews created before conversations
existed (or via the API directly) would otherwise be reachable only by URL.
Idempotent - safe to run repeatedly.

    cd backend
    python scripts/backfill_chats.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import SessionLocal  # noqa: E402
from app.models import Conversation, Review  # noqa: E402


def main() -> int:
    created = 0
    with SessionLocal() as db:
        conversations = db.query(Conversation).all()
        linked = {
            message.get("review_id")
            for conversation in conversations
            for message in (conversation.messages or [])
            if message.get("kind") == "review"
        }

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

    print(f"Created {created} chat(s) for existing reviews.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""SQLAlchemy ORM models: Review, Finding, Setting.

Mental model:
  * Review   = "one AI review of one Pull Request at one commit"
  * Finding  = "one problem found inside a review" (a row in the PR comment)
  * Setting  = "key/value overrides saved from the Settings page"

GIT CONCEPT (read me if you are new to Git):
A *commit* is an immutable snapshot of your project, identified by a SHA
(e.g. "9f2c1ab..."). A *Pull Request* is a proposal to merge one branch into
another; it is a *conversation* on top of commits. Every time you push a new
commit to the PR branch, the PR's head commit changes - that is why we store
`head_sha` on Review: it lets us detect "this exact commit was already
reviewed" and keeps reviews reproducible.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# --------------------------------------------------------------------------- #
# Enums
#
# Stored as plain VARCHAR instead of native PG ENUM types: adding a new value
# to a Postgres ENUM requires a migration with ALTER TYPE, which is exactly the
# kind of yak-shaving that ruins a demo. These Python enums still give us
# autocomplete and validation.
# --------------------------------------------------------------------------- #
class ReviewStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Category(str, Enum):
    BUG = "bug"
    SECURITY = "security"
    STYLE = "style"


class FindingSource(str, Enum):
    AI = "ai"
    STATIC = "static"  # pyflakes
    SECRET = "secret"  # regex scanner
    RULE = "rule"  # user-defined custom rule


# Lower number == more severe. Used for sorting everywhere (SQL + Python).
SEVERITY_RANK: dict[str, int] = {
    Severity.HIGH.value: 0,
    Severity.MEDIUM.value: 1,
    Severity.LOW.value: 2,
}


class Review(Base):
    """One review run for one PR at one head commit."""

    __tablename__ = "reviews"
    __table_args__ = (
        # Idempotency: GitHub retries webhook deliveries. Re-delivering the
        # same event must not create a second review for the same commit.
        UniqueConstraint("repo_name", "pr_number", "head_sha", name="uq_review_commit"),
        Index("ix_reviews_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- What was reviewed -------------------------------------------------
    repo_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pr_title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    pr_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pr_author: Mapped[str | None] = mapped_column(String(120), nullable=True)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # --- Lifecycle ---------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReviewStatus.QUEUED.value, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Stats -------------------------------------------------------------
    files_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    additions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Wall-clock duration in ms. Stored (not computed) so /api/stats is a
    # single cheap AVG() instead of Python-side date math.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Payloads ----------------------------------------------------------
    # Unified diff, stored so the dashboard keeps working even if the token
    # expires or the PR is force-pushed. Also powers the split diff viewer.
    diff_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # URL of the review we posted back to GitHub (nice "view on GitHub" link).
    github_review_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Where the review came from:
    #   "github" -> a pull_request webhook (or a PR URL submitted in the app)
    #   "diff"   -> a unified diff pasted into the "New review" page
    #   "code"   -> a file pasted into the "New review" page
    # Pasted reviews never call GitHub, so they work with no token and no
    # public webhook - which is what makes the platform usable on its own.
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="github", server_default="github"
    )

    # Generated pytest file for this review (editable/downloadable in the UI).
    generated_tests: Mapped[str | None] = mapped_column(Text, nullable=True)
    tests_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Timestamps --------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    findings: Mapped[list["Finding"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Review id={self.id} {self.repo_name}#{self.pr_number} status={self.status}>"


class Finding(Base):
    """A single issue found by the AI, pyflakes, or the secret scanner."""

    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_review_severity", "review_id", "severity"),
        Index("ix_findings_review_file", "review_id", "file_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Path relative to the repo root, exactly as GitHub reports it:
    # "backend/app/main.py" (no leading slash, forward slashes).
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # 1-based line number in the NEW version of the file. GitHub inline
    # comments are anchored to these numbers, so precision matters.
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)

    severity: Mapped[str] = mapped_column(
        String(10), nullable=False, default=Severity.MEDIUM.value
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False, default=Category.BUG.value)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.65)
    # The code at `line_number` when the review ran. Stored so the UI can show
    # a before/after diff and a "copy fixed code" button without re-reading the
    # source file (which may have changed since).
    original_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which engine produced this finding - lets the UI show a "pyflakes" chip
    # and lets us tune/dedupe by source later.
    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default=FindingSource.AI.value, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    review: Mapped[Review] = relationship(back_populates="findings")

    @property
    def severity_rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, 99)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Finding id={self.id} {self.file_path}:{self.line_number} "
            f"{self.severity}/{self.category} source={self.source}>"
        )


class Setting(Base):
    """Key/value store for runtime-configurable settings (Settings page).

    SECURITY NOTE, read before shipping this to real users:
    values in this table are stored as plain text. That is acceptable for a
    local hackathon demo, but in production you should encrypt them at rest
    (e.g. `pgcrypto`, AWS Secrets Manager, or a KMS-backed column type).
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Setting {self.key} secret={self.is_secret}>"


class Conversation(Base):
    """A saved chat in the workspace.

    Messages live in a JSON column on purpose: a conversation is always read
    and written as a whole, and keeping one row per chat means loading history
    is a single SELECT. Each message is a small dict so the shape can evolve
    without a migration:

        {"role": "user"|"assistant", "kind": "text"|"review"|"error",
         "content": str, "review_id": int|null, "created_at": iso8601}
    """

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_updated", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New chat")
    messages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Conversation id={self.id} title={self.title!r} messages={len(self.messages)}>"

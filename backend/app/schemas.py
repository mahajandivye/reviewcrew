"""Pydantic schemas = the API contract.

Two rules of thumb used here:
  * Never return ORM objects directly. Explicit response models mean a new DB
    column (e.g. a token) can never leak into a public response by accident.
  * Validate/limit pagination at the edge (`ge=1, le=100`) so one bad query
    string cannot make the database work overtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Category, FindingSource, ReviewStatus, Severity


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #
class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_path: str
    line_number: int
    severity: str
    category: str
    message: str
    suggestion: str | None = None
    original_snippet: str | None = None
    evidence: str | None = None
    confidence: float = 0.65
    source: str


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
class ReviewSummary(BaseModel):
    """Row in the dashboard's recent-reviews table (no nested findings)."""

    id: int
    repo_name: str
    pr_number: int
    pr_title: str
    pr_url: str | None = None
    status: str
    source: str = "github"  # github | diff | code
    files_changed: int = 0
    findings_count: int = 0
    high_severity_count: int = 0
    duration_seconds: float | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ReviewCreateRequest(BaseModel):
    """Body for POST /api/reviews - the in-app "New review" flow.

    Three entry points, all landing in the same pipeline:
      * source="pr"   + pr_url      -> fetch the PR and review the diff
      * source="diff" + diff        -> review a pasted unified diff
      * source="code" + code + file_path -> review a pasted file as a "new file"
      * source="files" + files      -> review a small multi-file project
    """

    source: Literal["pr", "diff", "code", "files"]
    pr_url: str | None = Field(default=None, max_length=512)
    diff: str | None = Field(default=None, max_length=500_000)
    code: str | None = Field(default=None, max_length=500_000)
    files: list["PastedFile"] | None = Field(default=None, max_length=20)
    file_path: str | None = Field(default=None, max_length=1024)
    title: str | None = Field(default=None, max_length=200)


class PastedFile(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    code: str = Field(default="", max_length=200_000)


class RulesPayload(BaseModel):
    rules: list["CustomRule"] = Field(default_factory=list, max_length=50)


class CustomRule(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    pattern: str = Field(min_length=1, max_length=500)
    message: str = Field(default="", max_length=400)
    severity: Literal["high", "medium", "low"] = "medium"
    category: Literal["bug", "security", "style"] = "bug"
    enabled: bool = True


class TestsOut(BaseModel):
    tests: str
    model: str = ""
    created_at: datetime | None = None


class ReviewDetail(ReviewSummary):
    """Review Detail page: everything about one review."""

    pr_author: str | None = None
    head_sha: str = ""
    additions: int = 0
    deletions: int = 0
    error_message: str | None = None
    github_review_url: str | None = None
    started_at: datetime | None = None
    generated_tests: str | None = None
    counts_by_severity: dict[str, int] = Field(default_factory=dict)
    findings: list[FindingOut] = Field(default_factory=list)


class ReviewListResponse(BaseModel):
    items: list[ReviewSummary]
    total: int
    page: int
    page_size: int
    pages: int


# --------------------------------------------------------------------------- #
# Dashboard stats
# --------------------------------------------------------------------------- #
class StatsResponse(BaseModel):
    total_reviews: int = 0
    reviews_in_progress: int = 0
    completed_reviews: int = 0
    failed_reviews: int = 0
    issues_found: int = 0
    high_severity_count: int = 0
    avg_review_seconds: float = 0.0
    reviews_last_7_days: int = 0
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    findings_by_category: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
class SettingsUpdate(BaseModel):
    """Request body for PATCH /api/settings.

    All fields optional: sending only `openai_model` changes only the model.
    Empty string means "clear this value".
    """

    github_token: str | None = Field(default=None, max_length=512)
    openai_api_key: str | None = Field(default=None, max_length=512)
    openai_model: str | None = Field(default=None, max_length=100)
    reviewer_persona: Literal["balanced", "security", "performance", "mentor"] | None = None
    openrouter_api_key: str | None = Field(default=None, max_length=512)
    chat_model: str | None = Field(default=None, max_length=120)
    post_pr_comments: bool | None = None


class SettingsOut(BaseModel):
    """Response for GET /api/settings.

    API keys are NEVER returned in full. Students often leak keys by piping
    `GET /settings` into a screenshot - `sk-...9f2a` is all we expose.
    """

    github_token: str = ""  # masked, e.g. "ghp_...a1b2"
    github_token_configured: bool = False
    openai_api_key: str = ""  # masked
    openai_api_key_configured: bool = False
    openai_model: str = ""
    reviewer_persona: str = "balanced"
    openrouter_api_key: str = ""  # masked
    openrouter_api_key_configured: bool = False
    chat_model: str = ""
    post_pr_comments: bool = True
    source: str = "database"  # where the effective value came from


# --------------------------------------------------------------------------- #
# Conversations (saved chats)
# --------------------------------------------------------------------------- #
class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    kind: Literal["text", "review", "error"] = "text"
    content: str = ""
    review_id: int | None = None
    created_at: str | None = None


class ConversationSummary(BaseModel):
    id: int
    title: str
    message_count: int = 0
    preview: str = ""
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessage] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    kind: Literal["text", "review", "error"] = "text"
    content: str = Field(default="", max_length=50_000)
    review_id: int | None = None


# --------------------------------------------------------------------------- #
# Chat (OpenRouter)
# --------------------------------------------------------------------------- #
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=50_000)


class ChatRequest(BaseModel):
    """The chat bar sends the visible conversation; the server adds context.

    Passing `review_id` attaches the findings and PR metadata for that review,
    which is what lets the user ask "why is this a bug?" and get an answer about
    *their* code instead of a generic one.
    """

    messages: list[ChatMessage] = Field(min_length=1, max_length=60)
    review_id: int | None = None
    model: str | None = Field(default=None, max_length=120)


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
class WebhookAck(BaseModel):
    status: str
    detail: str | None = None
    review_id: int | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    redis: str
    github_configured: bool
    openai_configured: bool


# --------------------------------------------------------------------------- #
# Diff viewer (Phase 4)
#
# The frontend must not re-parse a unified diff in JavaScript: line numbers are
# the anchor for every finding, and having two parsers would eventually
# disagree. The backend parses once and ships structured hunks.
# --------------------------------------------------------------------------- #
class DiffLineOut(BaseModel):
    kind: str  # "add" | "del" | "context"
    old_line: int | None = None
    new_line: int | None = None
    content: str


class DiffHunkOut(BaseModel):
    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section: str = ""
    lines: list[DiffLineOut] = Field(default_factory=list)


class DiffFileOut(BaseModel):
    path: str
    old_path: str | None = None
    status: str  # added | removed | modified | renamed
    language: str = "Plain text"
    additions: int = 0
    deletions: int = 0
    is_binary: bool = False
    hunks: list[DiffHunkOut] = Field(default_factory=list)


class ReviewDiffResponse(BaseModel):
    review_id: int
    has_diff: bool = False
    files: list[DiffFileOut] = Field(default_factory=list)


# Forward refs above ("PastedFile", "CustomRule") are defined after the models
# that use them; resolve them once the module is fully loaded.
ReviewCreateRequest.model_rebuild()
RulesPayload.model_rebuild()


# Re-exported so routers/services can validate against the enums without
# importing app.models (keeps layers a little cleaner).
__all__ = [
    "Category",
    "DiffFileOut",
    "DiffHunkOut",
    "DiffLineOut",
    "FindingOut",
    "FindingSource",
    "HealthResponse",
    "ReviewCreateRequest",
    "ReviewDetail",
    "ReviewDiffResponse",
    "ReviewListResponse",
    "ReviewStatus",
    "ReviewSummary",
    "SettingsOut",
    "SettingsUpdate",
    "Severity",
    "StatsResponse",
    "WebhookAck",
]

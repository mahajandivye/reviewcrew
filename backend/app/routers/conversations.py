"""Saved conversations - the workspace's chat history.

  GET    /api/conversations              list (newest activity first)
  POST   /api/conversations              create
  GET    /api/conversations/{id}         full transcript
  PATCH  /api/conversations/{id}         rename
  DELETE /api/conversations/{id}         delete
  POST   /api/conversations/{id}/messages  append one message

Messages are appended one at a time by the UI: the user's message before the
model call, the assistant's when the stream finishes (or fails). That means a
crashed stream still leaves a saved conversation rather than a lost one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging_config import get_logger
from app.models import Conversation, Review
from app.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationMessage,
    ConversationMessageIn,
    ConversationSummary,
    ConversationUpdate,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])

DEFAULT_TITLE = "New chat"
TITLE_CHARS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _preview(conversation: Conversation) -> str:
    for message in reversed(conversation.messages or []):
        text = (message.get("content") or "").strip()
        if text:
            return " ".join(text.split())[:120]
    return ""


def _summary(conversation: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        message_count=len(conversation.messages or []),
        preview=_preview(conversation),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _detail(conversation: Conversation) -> ConversationDetail:
    return ConversationDetail(
        **_summary(conversation).model_dump(),
        messages=[ConversationMessage(**message) for message in conversation.messages or []],
    )


def _get_or_404(db: Session, conversation_id: int) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("", response_model=list[ConversationSummary], summary="List saved chats")
def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[ConversationSummary]:
    rows = (
        db.execute(
            select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    return [_summary(row) for row in rows]


@router.post(
    "",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a conversation",
)
def create_conversation(
    payload: ConversationCreate, db: Session = Depends(get_db)
) -> ConversationDetail:
    title = (payload.title or DEFAULT_TITLE).strip()[:200] or DEFAULT_TITLE
    conversation = Conversation(title=title, messages=[])
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _detail(conversation)


@router.get("/{conversation_id}", response_model=ConversationDetail, summary="Get a chat")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)) -> ConversationDetail:
    return _detail(_get_or_404(db, conversation_id))


@router.patch("/{conversation_id}", response_model=ConversationSummary, summary="Rename a chat")
def rename_conversation(
    conversation_id: int, payload: ConversationUpdate, db: Session = Depends(get_db)
) -> ConversationSummary:
    conversation = _get_or_404(db, conversation_id)
    conversation.title = payload.title.strip()[:200]
    conversation.updated_at = _now()
    db.commit()
    db.refresh(conversation)
    return _summary(conversation)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a chat",
)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)) -> Response:
    conversation = _get_or_404(db, conversation_id)
    db.delete(conversation)
    db.commit()
    logger.info("Deleted conversation %s", conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessage,
    status_code=status.HTTP_201_CREATED,
    summary="Append a message",
)
def append_message(
    conversation_id: int, payload: ConversationMessageIn, db: Session = Depends(get_db)
) -> ConversationMessage:
    conversation = _get_or_404(db, conversation_id)

    review: Review | None = None
    if payload.review_id is not None:
        review = db.get(Review, payload.review_id)
        if review is None:
            raise HTTPException(status_code=404, detail="Review not found")

    message = {
        "role": payload.role,
        "kind": payload.kind,
        "content": payload.content,
        "review_id": payload.review_id,
        "created_at": _now().isoformat(),
    }

    # The first message names the conversation, the way a new chat gets its
    # title from its opening prompt.
    if conversation.title in ("", DEFAULT_TITLE):
        if payload.kind == "text" and payload.role == "user":
            title = " ".join(payload.content.split())[:TITLE_CHARS]
            if title:
                conversation.title = title
        elif payload.kind == "review" and review is not None:
            conversation.title = (review.pr_title or DEFAULT_TITLE)[:TITLE_CHARS]

    conversation.messages = [*(conversation.messages or []), message]
    conversation.updated_at = _now()
    db.commit()
    db.refresh(conversation)
    return ConversationMessage(**message)

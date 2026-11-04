"""POST /api/chat - the assistant behind the chat bar, via OpenRouter.

Why OpenRouter: one API, any model. The user picks a model in Settings and the
backend forwards to `https://openrouter.ai/api/v1/chat/completions`, which is
OpenAI-compatible.

Responses are streamed as Server-Sent Events so the UI renders tokens as they
arrive instead of freezing for five seconds. Each event is one JSON object:

    data: {"delta": "partial text"}
    data: {"error": "human readable problem"}
    data: [DONE]

Security: the API key never reaches the browser. The frontend only ever talks
to this endpoint.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.logging_config import get_logger
from app.models import SEVERITY_RANK, Review
from app.schemas import ChatRequest
from app.services.code_context import primary_code
from app.services.settings_service import get_effective_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

SYSTEM_PROMPT = """You are ReviewPilot, a code review assistant embedded in a \
review workspace. You are talking to the developer whose code is on screen.

Style:
- Be direct and technical. No filler, no praise, no "great question".
- Prefer concrete fixes. Show a short code snippet when it helps.
- If you are unsure, say what you would check instead of guessing.

Scope:
- Questions are usually about a specific finding, a diff, or how to fix it.
- The code under review may be attached below; use it. When the user says
  "this", "it", or "now optimise it", they mean that code.
- If the answer depends on code you cannot see, ask for that file or line.
- Never invent line numbers or file contents."""

# Context is injected as a system message. Keep it bounded: this runs on every
# turn, and a giant dump would crowd out the actual conversation.
MAX_CONTEXT_FINDINGS = 15
MAX_CONTEXT_CHARS = 9_000


def _sse(payload: dict[str, Any] | str) -> str:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {body}\n\n"


def _code_excerpt(review: Review, limit: int = 4500) -> str:
    """The code that was reviewed.

    This is what makes follow-ups work: without it, "now optimise this for
    memory" has nothing to optimise. For a pasted file every line is an
    addition, so the file can be rebuilt exactly from the stored diff.
    """
    if not review.diff_text:
        return ""

    if review.source in {"code", "files"}:
        return primary_code(review.diff_text)[:limit]

    if review.source == "diff":
        return review.diff_text[:limit]

    return ""


def _review_context(db: Session, review_id: int) -> str:
    """Compact description of the review the user is asking about."""
    review = db.get(Review, review_id)
    if review is None:
        return ""

    findings = sorted(
        review.findings,
        key=lambda f: (SEVERITY_RANK.get(f.severity, 99), f.file_path, f.line_number),
    )[:MAX_CONTEXT_FINDINGS]

    lines = [
        f"Repository: {review.repo_name}",
        f"Title: {review.pr_title}",
        f"Status: {review.status}",
        f"Files changed: {review.files_changed} (+{review.additions}/-{review.deletions})",
    ]

    code = _code_excerpt(review)
    if code:
        lines.append("")
        lines.append("Code under review:")
        lines.append("```")
        lines.append(code)
        lines.append("```")

    if findings:
        lines.append("")
        lines.append("Findings (most severe first):")
        for finding in findings:
            lines.append(
                f"- [{finding.severity}/{finding.category}] "
                f"{finding.file_path}:{finding.line_number} - {finding.message}"
            )
    else:
        lines.append("No findings were reported for this review.")

    context = "\n".join(lines)
    return context[:MAX_CONTEXT_CHARS]


def _upstream_payload(request: ChatRequest, model: str, context: str) -> dict[str, Any]:
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append(
            {"role": "system", "content": f"The review currently open:\n{context}"}
        )
    # Only the tail of the conversation matters; caps token spend on long chats.
    messages.extend({"role": m.role, "content": m.content} for m in request.messages[-20:])

    return {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }


def _stream_completion(
    *, api_key: str, base_url: str, model: str, payload: dict[str, Any]
) -> Generator[str, None, None]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # OpenRouter uses these for attribution; harmless if you do not care.
        "HTTP-Referer": settings.frontend_origins.split(",")[0],
        "X-Title": "ReviewPilot",
    }
    url = f"{base_url.rstrip('/')}/chat/completions"

    try:
        with httpx.Client(
            timeout=httpx.Timeout(settings.openai_timeout_seconds, connect=10.0)
        ) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", errors="replace")[:400]
                    logger.warning("OpenRouter error %s: %s", response.status_code, detail)
                    yield _sse(
                        {
                            "error": (
                                f"The model provider rejected the request "
                                f"({response.status_code}). Check the API key and model "
                                f"name in Settings."
                            )
                        }
                    )
                    return

                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield _sse({"delta": text})

    except httpx.HTTPError as exc:
        logger.warning("OpenRouter unreachable: %s", exc)
        yield _sse({"error": f"Could not reach the model provider: {exc}"})
    except Exception as exc:  # noqa: BLE001 - never leave the stream hanging
        logger.exception("Chat stream failed")
        yield _sse({"error": f"Chat failed: {type(exc).__name__}"})
    finally:
        yield _sse("[DONE]")


@router.post("", summary="Streaming chat completion (OpenRouter)")
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    effective = get_effective_settings(db)

    if not effective.openrouter_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No OpenRouter API key configured. Add one on the Settings page "
                "(or set OPENROUTER_API_KEY in .env)."
            ),
        )

    model = (request.model or effective.chat_model).strip()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No chat model configured.",
        )

    context = _review_context(db, request.review_id) if request.review_id else ""
    payload = _upstream_payload(request, model, context)

    logger.info(
        "chat: model=%s messages=%d context=%d chars",
        model,
        len(request.messages),
        len(context),
    )

    return StreamingResponse(
        _stream_completion(
            api_key=effective.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            model=model,
            payload=payload,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )

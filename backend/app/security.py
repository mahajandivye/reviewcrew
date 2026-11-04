"""GitHub webhook signature verification.

THE ONE THING TO UNDERSTAND
---------------------------
A webhook is just an HTTP POST to your public URL. Anyone who learns that URL
can POST `{"action": "opened", ...}` and make your app do work, spend OpenAI
credits, or deface PR comments.

GitHub solves this with a shared secret:
  1. You and GitHub both know `GITHUB_WEBHOOK_SECRET`.
  2. For each delivery GitHub computes
         HMAC-SHA256(secret, raw_request_body)
     and sends it in the `X-Hub-Signature-256: sha256=<hex>` header.
  3. You recompute the same digest over the body you received. If it matches,
     the sender knew the secret -> it really was GitHub.

Two implementation details that are easy to get wrong:

  * You must hash the **raw bytes** of the body, exactly as sent. If a
    framework parses JSON first and you re-serialise it, key order/whitespace
    can differ and the hash will never match. That is why the webhook route
    reads `await request.body()` and only then calls `json.loads`.

  * Compare with `hmac.compare_digest`, not `==`. `==` exits on the first
    differing byte, which leaks timing information that can be used to guess
    the signature byte by byte.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from app.logging_config import get_logger

logger = get_logger(__name__)

SIGNATURE_HEADER = "X-Hub-Signature-256"
SIGNATURE_PREFIX = "sha256="


class WebhookVerificationError(Exception):
    """Raised when a webhook delivery cannot be trusted."""


def compute_signature(raw_body: bytes, secret: str) -> str:
    """Return the value GitHub would put in the signature header."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """True only if `signature_header` is a valid signature of `raw_body`."""
    if not secret:
        # Misconfiguration, not a bad request: fail closed and log loudly.
        logger.error("Webhook rejected: GITHUB_WEBHOOK_SECRET is not configured")
        return False
    if not signature_header:
        logger.warning("Webhook rejected: missing %s header", SIGNATURE_HEADER)
        return False
    if not signature_header.startswith(SIGNATURE_PREFIX):
        logger.warning("Webhook rejected: unsupported signature algorithm")
        return False
    expected = compute_signature(raw_body, secret)
    # compare_digest is constant-time; `==` is not.
    if not hmac.compare_digest(expected, signature_header):
        logger.warning("Webhook rejected: signature mismatch")
        return False
    return True


def parse_payload(raw_body: bytes) -> dict[str, Any]:
    """Decode the raw body into a dict, raising WebhookVerificationError."""
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookVerificationError("Body is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise WebhookVerificationError("Payload must be a JSON object")
    return payload

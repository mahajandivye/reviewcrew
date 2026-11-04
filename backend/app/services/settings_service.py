"""Effective runtime settings = environment defaults + Settings-page overrides.

Precedence (highest first):
  1. value saved in the `settings` table from the dashboard
  2. value from `.env` / environment variables
  3. hardcoded default in app/config.py

This ordering is what lets a judge type an API key into the UI and see the
worker pick it up immediately, without a redeploy - while `.env` still works
for CI and containers.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as env_settings
from app.logging_config import get_logger
from app.models import Setting
from app.schemas import SettingsOut, SettingsUpdate

logger = get_logger(__name__)

# Only these keys may be written from the API. An allowlist prevents a
# malicious PATCH from setting arbitrary rows (e.g. "database_url").
WRITABLE_KEYS = {
    "github_token": True,  # True == secret
    "openai_api_key": True,
    "openai_model": False,
    "reviewer_persona": False,
    "openrouter_api_key": True,
    "chat_model": False,
    "post_pr_comments": False,
}


@dataclass(slots=True)
class EffectiveSettings:
    """What the review worker / chat assistant actually uses."""

    github_token: str
    openai_api_key: str
    openai_model: str
    openrouter_api_key: str
    chat_model: str
    post_pr_comments: bool
    reviewer_persona: str = "balanced"
    openai_base_url: str = ""

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def chat_enabled(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def github_enabled(self) -> bool:
        return bool(self.github_token)


def mask_secret(value: str) -> str:
    """`sk-proj-abcdef123456` -> `sk-p...(hidden)...3456`."""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:4]}...(hidden)...{value[-4:]}"


def _read_db_overrides(db: Session) -> dict[str, str]:
    try:
        rows = db.execute(select(Setting)).scalars().all()
    except Exception:  # noqa: BLE001 - table may not exist yet on first boot
        # Roll back or the session stays in an aborted transaction (Postgres),
        # which would break every later query in the same task/request.
        db.rollback()
        logger.warning("Could not read the settings table; falling back to .env")
        return {}
    return {row.key: row.value for row in rows}


def _as_bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_effective_settings(db: Session) -> EffectiveSettings:
    overrides = _read_db_overrides(db)
    openrouter_key = overrides.get("openrouter_api_key") or env_settings.openrouter_api_key
    review_key = (
        overrides.get("openai_api_key")
        or env_settings.openai_api_key
        or openrouter_key
    )
    uses_openrouter = bool(review_key) and (
        review_key.startswith("sk-or-") or review_key == openrouter_key
    )
    review_model = overrides.get("openai_model") or env_settings.openai_model
    if uses_openrouter and "/" not in review_model:
        review_model = f"openai/{review_model}"

    return EffectiveSettings(
        github_token=overrides.get("github_token") or env_settings.github_token,
        openai_api_key=review_key,
        openai_model=review_model,
        openai_base_url=(
            env_settings.openai_base_url
            or (env_settings.openrouter_base_url if uses_openrouter else "")
        ),
        reviewer_persona=overrides.get("reviewer_persona") or "balanced",
        openrouter_api_key=openrouter_key,
        chat_model=overrides.get("chat_model") or env_settings.chat_model,
        post_pr_comments=_as_bool(overrides.get("post_pr_comments"), env_settings.post_pr_comments),
    )


def read_public_settings(db: Session) -> SettingsOut:
    """Masked view for GET /api/settings."""
    effective = get_effective_settings(db)
    overrides = _read_db_overrides(db)
    return SettingsOut(
        github_token=mask_secret(effective.github_token),
        github_token_configured=bool(effective.github_token),
        openai_api_key=mask_secret(effective.openai_api_key),
        openai_api_key_configured=bool(effective.openai_api_key),
        openai_model=effective.openai_model,
        reviewer_persona=effective.reviewer_persona,
        openrouter_api_key=mask_secret(effective.openrouter_api_key),
        openrouter_api_key_configured=bool(effective.openrouter_api_key),
        chat_model=effective.chat_model,
        post_pr_comments=effective.post_pr_comments,
        source="database" if overrides else "environment",
    )


def update_settings(db: Session, payload: SettingsUpdate) -> SettingsOut:
    """Upsert only the fields present in the request.

    Sending `""` clears the stored override, so the `.env` value takes over
    again - that is the "reset" behaviour the UI needs.
    """
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key not in WRITABLE_KEYS:
            continue
        if value is None:
            continue
        stored = str(value).lower() if isinstance(value, bool) else str(value).strip()
        setting = db.get(Setting, key)
        if setting is None:
            setting = Setting(key=key, value=stored, is_secret=WRITABLE_KEYS[key])
            db.add(setting)
        else:
            setting.value = stored
    db.commit()
    logger.info("Settings updated: %s", sorted(changes.keys()))
    return read_public_settings(db)

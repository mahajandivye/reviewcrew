"""Application configuration.

Everything that can change between environments lives here and is read from
environment variables (or a `.env` file). Nothing in this module prints or
logs secret values.

Why this matters for a hackathon: judges/graders often ask "how do I run it?".
The answer is always `copy .env.example .env`, fill 3 values, done.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[1] == backend/ , parents[2] == repo root
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Typed, validated view of the environment."""

    model_config = SettingsConfigDict(
        # Both locations are tried in order; the repo-root .env wins.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_name: str = "ReviewPilot"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    # --- Infrastructure ----------------------------------------------------
    database_url: str = (
        "postgresql+psycopg://reviewpilot:reviewpilot@localhost:5432/reviewpilot"
    )
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False

    # --- GitHub ------------------------------------------------------------
    github_webhook_secret: str = ""
    github_token: str = ""
    github_api_url: str = "https://api.github.com"

    # --- OpenAI (the review engine) ----------------------------------------
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = ""
    openai_timeout_seconds: float = 60.0

    # --- OpenRouter (the in-app chat assistant) ----------------------------
    # Separate from the review engine on purpose: you might review with OpenAI
    # directly and chat through OpenRouter (or vice versa).
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    chat_model: str = "openai/gpt-4o-mini"

    # --- Review behaviour --------------------------------------------------
    post_pr_comments: bool = True
    max_diff_chars: int = 40_000
    max_findings: int = Field(default=50, ge=1, le=500)

    # --- CORS --------------------------------------------------------------
    frontend_origins: str = "http://localhost:5174,http://127.0.0.1:5174"

    # ------------------------------------------------------------------ #
    # Validators
    # ------------------------------------------------------------------ #
    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        """Accept the URL formats hosting providers hand you.

        Heroku/Render style URLs start with `postgres://`, which SQLAlchemy no
        longer understands. We normalise them and default to the psycopg 3
        driver, which is what requirements.txt installs.
        """
        value = value.strip()
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql+psycopg://", 1)
        elif value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.strip().upper()

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #
    @property
    def cors_origins(self) -> list[str]:
        """`FRONTEND_ORIGINS=a,b` -> ["a", "b"]."""
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def github_configured(self) -> bool:
        return bool(self.github_token and self.github_webhook_secret)

    def safe_summary(self) -> dict[str, object]:
        """Loggable snapshot with secrets replaced by a boolean."""
        return {
            "environment": self.environment,
            "database": self.database_url.split("@")[-1],  # never log credentials
            "redis": self.redis_url.split("@")[-1],
            "github_token_set": bool(self.github_token),
            "webhook_secret_set": bool(self.github_webhook_secret),
            "openai_key_set": bool(self.openai_api_key),
            "openai_model": self.openai_model,
            "openrouter_key_set": bool(self.openrouter_api_key),
            "chat_model": self.chat_model,
            "post_pr_comments": self.post_pr_comments,
        }


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed once per process.

    `get_settings.cache_clear()` is used by the tests to reload env vars.
    """
    return Settings()


settings = get_settings()

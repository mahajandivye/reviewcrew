"""FastAPI application factory.

Run locally:
    cd backend
    uvicorn app.main:app --reload --port 8000

Interactive API docs (try every endpoint from the browser):
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.logging_config import configure_logging, get_logger
from app.routers import chat as chat_router
from app.routers import conversations as conversations_router
from app.routers import reviews as reviews_router
from app.routers import rules as rules_router
from app.routers import settings as settings_router
from app.routers import stats as stats_router
from app.routers import webhooks as webhooks_router
from app.schemas import HealthResponse

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    logger.info("%s v%s starting (%s)", settings.app_name, settings.app_version, settings.environment)
    for key, value in settings.safe_summary().items():
        logger.info("  %-20s %s", key, value)
    if not settings.github_webhook_secret:
        logger.warning("GITHUB_WEBHOOK_SECRET is empty - all webhooks will be rejected")
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY is empty - reviews will use static analysis only")
    yield
    logger.info("%s shutting down", settings.app_name)


def create_app() -> FastAPI:
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-powered pull request reviews. GitHub webhook in, inline PR comments out, "
            "dashboard on top."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # --- CORS ---------------------------------------------------------- #
    # The browser refuses cross-origin XHR unless the server opts in: the
    # React dev server is on :5173 and this API on :8000. `allow_origins` must
    # list exact origins (not "*") because we send credentials-capable requests.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # --- routes -------------------------------------------------------- #
    app.include_router(webhooks_router.router)  # /webhook/github
    app.include_router(reviews_router.router, prefix="/api")
    app.include_router(stats_router.router, prefix="/api")
    app.include_router(settings_router.router, prefix="/api")
    app.include_router(chat_router.router, prefix="/api")
    app.include_router(conversations_router.router, prefix="/api")
    app.include_router(rules_router.router, prefix="/api")

    @app.get("/", tags=["meta"], summary="Service banner")
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health", response_model=HealthResponse, tags=["meta"], summary="Health check")
    def health(db: Session = Depends(get_db)) -> HealthResponse:
        """Liveness + dependency check.

        Reporting Redis as "unavailable" while the API is up is intentional:
        it tells you that webhooks will be accepted but jobs will not run.
        """
        database = "ok"
        try:
            db.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            database = f"unavailable: {type(exc).__name__}"
            logger.warning("Health check: database unreachable (%s)", exc)

        if settings.celery_task_always_eager:
            redis_status = "not required (inline review mode)"
        else:
            redis_status = "ok"
            try:
                import redis as redis_lib

                client = redis_lib.from_url(
                    settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
                )
                client.ping()
            except Exception as exc:  # noqa: BLE001
                redis_status = f"unavailable: {type(exc).__name__}"
                logger.warning("Health check: redis unreachable (%s)", exc)

        return HealthResponse(
            status="ok" if database == "ok" else "degraded",
            version=settings.app_version,
            environment=settings.environment,
            database=database,
            redis=redis_status,
            github_configured=bool(settings.github_token and settings.github_webhook_secret),
            openai_configured=bool(settings.openai_api_key),
        )

    # --- error handling ------------------------------------------------- #
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Log the traceback, return JSON (never an HTML error page).

        HTTPException is handled by FastAPI before reaching this, so this is
        genuinely the "we did not expect this" path.
        """
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        payload: dict[str, Any] = {
            "detail": "Internal server error",
            "path": request.url.path,
        }
        # Leak the exception type (not the traceback) only outside production.
        if not settings.is_production:
            payload["error"] = f"{type(exc).__name__}: {exc}"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=payload
        )

    return app


app = create_app()

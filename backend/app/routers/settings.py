"""API-backed settings (the Settings page in Phase 3 writes here).

  GET   /api/settings -> masked view of the effective configuration
  PATCH /api/settings -> upsert one or more values

SECURITY: reads always mask secrets. Writes never echo a secret back either,
so the only way to see a full key is to look at the database or .env.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import SettingsOut, SettingsUpdate
from app.services.settings_service import read_public_settings, update_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut, summary="Read settings (masked)")
def get_settings(db: Session = Depends(get_db)) -> SettingsOut:
    return read_public_settings(db)


@router.patch("", response_model=SettingsOut, summary="Update settings")
def patch_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsOut:
    return update_settings(db, payload)

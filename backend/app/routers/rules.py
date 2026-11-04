"""Custom rules API: GET the list, PUT the whole list."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import CustomRule, RulesPayload
from app.services.rules_service import RuleError, load_rules, save_rules

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=list[CustomRule], summary="List custom rules")
def get_rules(db: Session = Depends(get_db)) -> list[CustomRule]:
    return [CustomRule(**rule) for rule in load_rules(db)]


@router.put("", response_model=list[CustomRule], summary="Replace custom rules")
def put_rules(payload: RulesPayload, db: Session = Depends(get_db)) -> list[CustomRule]:
    try:
        saved = save_rules(db, [rule.model_dump() for rule in payload.rules])
    except RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [CustomRule(**rule) for rule in saved]

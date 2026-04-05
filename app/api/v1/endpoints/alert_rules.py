from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full
from app.db.session import get_db
from app.models.alert_rule import AlertRule, AlertRuleUnit
from app.models.organization import Organization, OrganizationStatus
from app.models.unit import Unit
from app.models.user import User
from app.schemas.alert_rule import (
    AlertRuleCreate,
    AlertRuleDeleteOut,
    AlertRuleOut,
    AlertRuleUnitsAssign,
    AlertRuleUnitsOut,
    AlertRuleUnitsUnassign,
    AlertRuleUpdate,
)
from app.utils.json_normalization import generate_fingerprint, normalize_json

router = APIRouter()


def _organization_is_active(db: Session, organization_id: UUID) -> bool:
    org = (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.status == OrganizationStatus.ACTIVE,
        )
        .first()
    )
    return org is not None


def _validate_unit_ids(
    db: Session,
    organization_id: UUID,
    unit_ids: list[UUID],
) -> list[UUID]:
    unique_unit_ids = list(dict.fromkeys(unit_ids))

    rows = (
        db.query(Unit.id)
        .filter(
            Unit.organization_id == organization_id,
            Unit.deleted_at.is_(None),
            Unit.id.in_(unique_unit_ids),
        )
        .all()
    )
    valid_ids = {row.id for row in rows}

    missing = [str(unit_id) for unit_id in unique_unit_ids if unit_id not in valid_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Todas las unidades deben pertenecer a la organización del usuario "
                f"y estar activas. unit_ids inválidos: {', '.join(missing)}"
            ),
        )

    return unique_unit_ids


def _build_rule_out(db: Session, rule: AlertRule) -> AlertRuleOut:
    unit_rows = (
        db.query(AlertRuleUnit.unit_id)
        .filter(AlertRuleUnit.rule_id == rule.id)
        .order_by(AlertRuleUnit.created_at.asc())
        .all()
    )

    return AlertRuleOut(
        id=rule.id,
        organization_id=rule.organization_id,
        created_by=rule.created_by,
        name=rule.name,
        type=rule.type,
        config=rule.config,
        unit_ids=[row.unit_id for row in unit_rows],
        is_active=rule.is_active,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _get_active_rule_or_404(
    db: Session, rule_id: UUID, organization_id: UUID
) -> AlertRule:
    rule = (
        db.query(AlertRule)
        .filter(
            AlertRule.id == rule_id,
            AlertRule.organization_id == organization_id,
            AlertRule.is_active.is_(True),
        )
        .first()
    )

    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regla no encontrada",
        )

    return rule


@router.post("", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
def create_alert_rule(
    payload: AlertRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    normalized_config = normalize_json(payload.config)
    fingerprint = generate_fingerprint(
        current_user.organization_id, payload.type, normalized_config
    )

    rule = AlertRule(
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        name=payload.name,
        type=payload.type,
        config=normalized_config,
        fingerprint=fingerprint,
        is_active=True,
    )
    db.add(rule)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(AlertRule).filter(AlertRule.fingerprint == fingerprint).first()
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"id": str(existing.id), "message": "Regla ya existente"},
        )

    if payload.unit_ids:
        valid_unit_ids = _validate_unit_ids(
            db, current_user.organization_id, payload.unit_ids
        )
        for unit_id in valid_unit_ids:
            db.add(AlertRuleUnit(rule_id=rule.id, unit_id=unit_id))

    db.commit()
    db.refresh(rule)

    return _build_rule_out(db, rule)


@router.get("", response_model=list[AlertRuleOut])
def list_alert_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    type_filter: str | None = Query(None, alias="type"),
    unit_id: UUID | None = Query(None),
):
    if not _organization_is_active(db, current_user.organization_id):
        return []

    query = db.query(AlertRule).filter(
        AlertRule.organization_id == current_user.organization_id,
        AlertRule.is_active.is_(True),
    )

    if type_filter:
        query = query.filter(AlertRule.type == type_filter)

    if unit_id:
        _validate_unit_ids(db, current_user.organization_id, [unit_id])
        query = query.join(AlertRuleUnit, AlertRuleUnit.rule_id == AlertRule.id).filter(
            AlertRuleUnit.unit_id == unit_id
        )

    rules = query.order_by(AlertRule.created_at.desc()).all()
    return [_build_rule_out(db, rule) for rule in rules]


@router.get("/{rule_id}", response_model=AlertRuleOut)
def get_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    if not _organization_is_active(db, current_user.organization_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regla no encontrada",
        )

    rule = _get_active_rule_or_404(db, rule_id, current_user.organization_id)

    return _build_rule_out(db, rule)


@router.patch("/{rule_id}", response_model=AlertRuleOut)
def update_alert_rule(
    rule_id: UUID,
    payload: AlertRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    rule = _get_active_rule_or_404(db, rule_id, current_user.organization_id)

    update_data = payload.model_dump(exclude_unset=True)

    if "config" in update_data:
        update_data["config"] = normalize_json(update_data["config"])

    unit_ids = update_data.pop("unit_ids", None)
    for field, value in update_data.items():
        setattr(rule, field, value)

    rule.fingerprint = generate_fingerprint(
        rule.organization_id, rule.type, rule.config
    )

    if unit_ids is not None:
        valid_unit_ids = _validate_unit_ids(db, current_user.organization_id, unit_ids)
        db.query(AlertRuleUnit).filter(AlertRuleUnit.rule_id == rule.id).delete()
        for unit_id in valid_unit_ids:
            db.add(AlertRuleUnit(rule_id=rule.id, unit_id=unit_id))

    rule.updated_at = datetime.utcnow()

    db.add(rule)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fingerprint = rule.fingerprint
        existing = (
            db.query(AlertRule)
            .filter(
                AlertRule.fingerprint == fingerprint,
                AlertRule.id != rule_id,
            )
            .first()
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"id": str(existing.id), "message": "Regla ya existente"},
        )

    db.refresh(rule)

    return _build_rule_out(db, rule)


@router.delete("/{rule_id}", response_model=AlertRuleDeleteOut)
def delete_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    rule = _get_active_rule_or_404(db, rule_id, current_user.organization_id)

    rule.is_active = False
    rule.updated_at = datetime.utcnow()

    db.add(rule)
    db.commit()

    return AlertRuleDeleteOut(
        message="Regla desactivada exitosamente",
        rule_id=rule_id,
        is_active=False,
    )


@router.post("/{rule_id}/units", response_model=AlertRuleUnitsOut)
def assign_units_to_rule(
    rule_id: UUID,
    payload: AlertRuleUnitsAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    rule = _get_active_rule_or_404(db, rule_id, current_user.organization_id)
    valid_unit_ids = _validate_unit_ids(
        db, current_user.organization_id, payload.unit_ids
    )

    existing_rows = (
        db.query(AlertRuleUnit.unit_id)
        .filter(
            AlertRuleUnit.rule_id == rule.id,
            AlertRuleUnit.unit_id.in_(valid_unit_ids),
        )
        .all()
    )
    existing_ids = {row.unit_id for row in existing_rows}

    for unit_id in valid_unit_ids:
        if unit_id not in existing_ids:
            db.add(AlertRuleUnit(rule_id=rule.id, unit_id=unit_id))

    rule.updated_at = datetime.utcnow()
    db.add(rule)
    db.commit()

    return AlertRuleUnitsOut(rule_id=rule.id, unit_ids=valid_unit_ids)


@router.delete("/{rule_id}/units", response_model=AlertRuleUnitsOut)
def unassign_units_from_rule(
    rule_id: UUID,
    payload: AlertRuleUnitsUnassign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    rule = _get_active_rule_or_404(db, rule_id, current_user.organization_id)
    target_ids = list(dict.fromkeys(payload.unit_ids))

    db.query(AlertRuleUnit).filter(
        AlertRuleUnit.rule_id == rule.id,
        AlertRuleUnit.unit_id.in_(target_ids),
    ).delete(synchronize_session=False)

    rule.updated_at = datetime.utcnow()
    db.add(rule)
    db.commit()

    return AlertRuleUnitsOut(rule_id=rule.id, unit_ids=target_ids)

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full, get_rules_kafka_producer
from app.db.session import get_db
from app.models.alert import Alert
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
from app.services.messaging.kafka_producer import RulesKafkaProducer
from app.utils.json_normalization import generate_fingerprint, normalize_json

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_utc_iso_z(value: datetime | None) -> str:
    dt = value or datetime.utcnow()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def _build_upsert_event_payload(db: Session, rule: AlertRule) -> dict:
    rule_out = _build_rule_out(db, rule)

    # Get units with their names
    unit_rows = (
        db.query(Unit.id, Unit.name)
        .join(AlertRuleUnit, AlertRuleUnit.unit_id == Unit.id)
        .filter(AlertRuleUnit.rule_id == rule.id)
        .order_by(AlertRuleUnit.created_at.asc())
        .all()
    )

    units_context = [
        {
            "id": str(row.id),
            "name": row.name,
        }
        for row in unit_rows
    ]

    return {
        "operation": "UPSERT",
        "rule": {
            "id": str(rule_out.id),
            "organization_id": str(rule_out.organization_id),
            "name": rule_out.name,
            "type": rule_out.type,
            "config": rule_out.config,
            "unit_ids": [str(unit_id) for unit_id in rule_out.unit_ids],
            "is_active": rule_out.is_active,
            "updated_at": _to_utc_iso_z(rule_out.updated_at),
        },
        "context": {
            "units": units_context,
        },
    }


def _build_delete_event_payload(rule: AlertRule) -> dict:
    return {
        "operation": "DELETE",
        "rule_id": str(rule.id),
        "updated_at": _to_utc_iso_z(rule.updated_at),
    }


def _duplicate_rule_response(existing: AlertRule | None) -> JSONResponse:
    message = (
        "Ya existe una regla con el mismo tipo y configuracion para esta organizacion"
    )

    content = {
        "message": message,
        "detail": (
            "El fingerprint se genera con organization_id, type y config normalizado. "
            "Cambia el tipo o la configuracion de la regla para crear una nueva."
        ),
    }

    if existing:
        content["id"] = str(existing.id)
        content["existing_rule"] = {
            "id": str(existing.id),
            "name": existing.name,
            "type": existing.type,
            "is_active": existing.is_active,
        }

    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=content,
    )


def _publish_rule_event(
    producer: RulesKafkaProducer,
    payload: dict,
    endpoint: str,
    organization_id: UUID,
) -> None:
    rule_id = payload.get("rule_id") or payload.get("rule", {}).get("id")
    try:
        published = producer.publish_rule_update(payload=payload, key=rule_id)
    except Exception:
        logger.exception(
            "[ALERT RULES] Excepcion inesperada publicando evento en Kafka.",
            extra={
                "extra_data": {
                    "endpoint": endpoint,
                    "operation": payload.get("operation"),
                    "rule_id": rule_id,
                    "organization_id": str(organization_id),
                }
            },
        )
        return

    if not published:
        logger.error(
            "[ALERT RULES] Fallo publicando evento en Kafka.",
            extra={
                "extra_data": {
                    "endpoint": endpoint,
                    "operation": payload.get("operation"),
                    "rule_id": rule_id,
                    "organization_id": str(organization_id),
                }
            },
        )


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
    rules_kafka_producer: RulesKafkaProducer = Depends(get_rules_kafka_producer),
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
        return _duplicate_rule_response(existing)

    if payload.unit_ids:
        valid_unit_ids = _validate_unit_ids(
            db, current_user.organization_id, payload.unit_ids
        )
        for unit_id in valid_unit_ids:
            db.add(AlertRuleUnit(rule_id=rule.id, unit_id=unit_id))

    db.commit()
    db.refresh(rule)

    kafka_payload = _build_upsert_event_payload(db, rule)
    _publish_rule_event(
        rules_kafka_producer,
        kafka_payload,
        endpoint="create_alert_rule",
        organization_id=current_user.organization_id,
    )

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
    rules_kafka_producer: RulesKafkaProducer = Depends(get_rules_kafka_producer),
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
        return _duplicate_rule_response(existing)

    db.refresh(rule)

    kafka_payload = _build_upsert_event_payload(db, rule)
    _publish_rule_event(
        rules_kafka_producer,
        kafka_payload,
        endpoint="update_alert_rule",
        organization_id=current_user.organization_id,
    )

    return _build_rule_out(db, rule)


@router.delete("/{rule_id}", response_model=AlertRuleDeleteOut)
def delete_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    rules_kafka_producer: RulesKafkaProducer = Depends(get_rules_kafka_producer),
):
    rule = _get_active_rule_or_404(db, rule_id, current_user.organization_id)

    deleted_at = datetime.utcnow()
    rule.updated_at = deleted_at
    kafka_payload = _build_delete_event_payload(rule)

    db.query(AlertRuleUnit).filter(AlertRuleUnit.rule_id == rule.id).delete(
        synchronize_session=False
    )
    db.query(Alert).filter(Alert.rule_id == rule.id).update(
        {Alert.rule_id: None},
        synchronize_session=False,
    )
    db.delete(rule)
    db.commit()

    _publish_rule_event(
        rules_kafka_producer,
        kafka_payload,
        endpoint="delete_alert_rule",
        organization_id=current_user.organization_id,
    )

    return AlertRuleDeleteOut(
        message="Regla eliminada exitosamente",
        rule_id=rule_id,
        deleted=True,
    )


@router.post("/{rule_id}/units", response_model=AlertRuleUnitsOut)
def assign_units_to_rule(
    rule_id: UUID,
    payload: AlertRuleUnitsAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    rules_kafka_producer: RulesKafkaProducer = Depends(get_rules_kafka_producer),
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

    db.refresh(rule)
    kafka_payload = _build_upsert_event_payload(db, rule)
    _publish_rule_event(
        rules_kafka_producer,
        kafka_payload,
        endpoint="assign_units_to_rule",
        organization_id=current_user.organization_id,
    )

    return AlertRuleUnitsOut(rule_id=rule.id, unit_ids=valid_unit_ids)


@router.delete("/{rule_id}/units", response_model=AlertRuleUnitsOut)
def unassign_units_from_rule(
    rule_id: UUID,
    payload: AlertRuleUnitsUnassign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    rules_kafka_producer: RulesKafkaProducer = Depends(get_rules_kafka_producer),
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

    db.refresh(rule)
    kafka_payload = _build_upsert_event_payload(db, rule)
    _publish_rule_event(
        rules_kafka_producer,
        kafka_payload,
        endpoint="unassign_units_from_rule",
        organization_id=current_user.organization_id,
    )

    return AlertRuleUnitsOut(rule_id=rule.id, unit_ids=target_ids)

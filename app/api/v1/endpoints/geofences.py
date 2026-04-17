import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full, get_geofences_kafka_producer
from app.db.session import get_db
from app.models.geofence import Geofence, GeofenceCell
from app.models.user import User
from app.schemas.geofence import (
    GeofenceCreate,
    GeofenceDeleteOut,
    GeofenceOut,
    GeofenceUpdate,
)
from app.services.messaging.kafka_producer import GeofencesKafkaProducer

router = APIRouter()
logger = logging.getLogger(__name__)


def _unique_h3_indexes(h3_indexes: list[int]) -> list[int]:
    return list(dict.fromkeys(h3_indexes))


def _build_geofence_out(db: Session, geofence: Geofence) -> GeofenceOut:
    rows = (
        db.query(GeofenceCell.h3_index)
        .filter(GeofenceCell.geofence_id == geofence.id)
        .order_by(GeofenceCell.h3_index.asc())
        .all()
    )

    return GeofenceOut(
        id=geofence.id,
        organization_id=geofence.organization_id,
        created_by=geofence.created_by,
        name=geofence.name,
        description=geofence.description,
        config=geofence.config,
        h3_indexes=[row.h3_index for row in rows],
        is_active=geofence.is_active,
        created_at=geofence.created_at,
        updated_at=geofence.updated_at,
    )


def _to_utc_iso_z(value: datetime | None) -> str:
    dt = value or datetime.utcnow()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def _build_upsert_event_payload(db: Session, geofence: Geofence) -> dict:
    geofence_out = _build_geofence_out(db, geofence)
    return {
        "event_id": str(uuid4()),
        "event_type": "UPSERT",
        "entity": "geofence",
        "timestamp": _to_utc_iso_z(datetime.utcnow()),
        "organization_id": str(geofence_out.organization_id),
        "data": {
            "id": str(geofence_out.id),
            "created_by": str(geofence_out.created_by),
            "name": geofence_out.name,
            "description": geofence_out.description or "",
            "is_active": geofence_out.is_active,
            "config": geofence_out.config,
            "cells": geofence_out.h3_indexes,
            "updated_at": _to_utc_iso_z(geofence_out.updated_at),
        },
    }


def _build_delete_event_payload(geofence_id: UUID, organization_id: UUID) -> dict:
    return {
        "event_id": str(uuid4()),
        "event_type": "DELETE",
        "entity": "geofence",
        "timestamp": _to_utc_iso_z(datetime.utcnow()),
        "organization_id": str(organization_id),
        "data": {
            "id": str(geofence_id),
        },
    }


def _publish_geofence_event(
    producer: GeofencesKafkaProducer,
    payload: dict,
    endpoint: str,
    geofence_id: UUID,
    organization_id: UUID,
) -> None:
    try:
        published = producer.publish_update(payload=payload, key=str(geofence_id))
    except Exception:
        logger.exception(
            "[GEOFENCES] Excepcion inesperada publicando evento en Kafka.",
            extra={
                "extra_data": {
                    "endpoint": endpoint,
                    "event_type": payload.get("event_type"),
                    "event_id": payload.get("event_id"),
                    "geofence_id": str(geofence_id),
                    "organization_id": str(organization_id),
                }
            },
        )
        return

    if not published:
        logger.error(
            "[GEOFENCES] Fallo publicando evento en Kafka.",
            extra={
                "extra_data": {
                    "endpoint": endpoint,
                    "event_type": payload.get("event_type"),
                    "event_id": payload.get("event_id"),
                    "geofence_id": str(geofence_id),
                    "organization_id": str(organization_id),
                }
            },
        )


def _get_active_geofence_or_404(
    db: Session, geofence_id: UUID, organization_id: UUID
) -> Geofence:
    geofence = (
        db.query(Geofence)
        .filter(
            Geofence.id == geofence_id,
            Geofence.organization_id == organization_id,
            Geofence.is_active.is_(True),
        )
        .first()
    )

    if not geofence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Geocerca no encontrada",
        )

    return geofence


@router.post("", response_model=GeofenceOut, status_code=status.HTTP_201_CREATED)
def create_geofence(
    payload: GeofenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    geofences_kafka_producer: GeofencesKafkaProducer = Depends(
        get_geofences_kafka_producer
    ),
):
    geofence = Geofence(
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        name=payload.name,
        description=payload.description,
        config=payload.config,
        is_active=True,
    )

    try:
        db.add(geofence)
        db.flush()

        for h3_index in _unique_h3_indexes(payload.h3_indexes):
            db.add(GeofenceCell(geofence_id=geofence.id, h3_index=h3_index))

        db.commit()
        db.refresh(geofence)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo crear la geocerca por conflicto de integridad",
        )

    kafka_payload = _build_upsert_event_payload(db, geofence)
    _publish_geofence_event(
        geofences_kafka_producer,
        kafka_payload,
        endpoint="create_geofence",
        geofence_id=geofence.id,
        organization_id=current_user.organization_id,
    )

    return _build_geofence_out(db, geofence)


@router.get("", response_model=list[GeofenceOut])
def list_geofences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    geofences = (
        db.query(Geofence)
        .filter(
            Geofence.organization_id == current_user.organization_id,
            Geofence.is_active.is_(True),
        )
        .order_by(Geofence.created_at.desc())
        .all()
    )

    return [_build_geofence_out(db, geofence) for geofence in geofences]


@router.get("/{geofence_id}", response_model=GeofenceOut)
def get_geofence(
    geofence_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    geofence = _get_active_geofence_or_404(
        db, geofence_id, current_user.organization_id
    )
    return _build_geofence_out(db, geofence)


@router.patch("/{geofence_id}", response_model=GeofenceOut)
def update_geofence(
    geofence_id: UUID,
    payload: GeofenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    geofences_kafka_producer: GeofencesKafkaProducer = Depends(
        get_geofences_kafka_producer
    ),
):
    geofence = _get_active_geofence_or_404(
        db, geofence_id, current_user.organization_id
    )

    update_data = payload.model_dump(exclude_unset=True)
    h3_indexes = update_data.pop("h3_indexes", None)

    for field, value in update_data.items():
        setattr(geofence, field, value)

    try:
        if h3_indexes is not None:
            db.query(GeofenceCell).filter(
                GeofenceCell.geofence_id == geofence.id
            ).delete(synchronize_session=False)
            for h3_index in _unique_h3_indexes(h3_indexes):
                db.add(GeofenceCell(geofence_id=geofence.id, h3_index=h3_index))

        geofence.updated_at = datetime.utcnow()
        db.add(geofence)
        db.commit()
        db.refresh(geofence)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo actualizar la geocerca por conflicto de integridad",
        )

    kafka_payload = _build_upsert_event_payload(db, geofence)
    _publish_geofence_event(
        geofences_kafka_producer,
        kafka_payload,
        endpoint="update_geofence",
        geofence_id=geofence.id,
        organization_id=current_user.organization_id,
    )

    return _build_geofence_out(db, geofence)


@router.delete("/{geofence_id}", response_model=GeofenceDeleteOut)
def delete_geofence(
    geofence_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    geofences_kafka_producer: GeofencesKafkaProducer = Depends(
        get_geofences_kafka_producer
    ),
):
    geofence = _get_active_geofence_or_404(
        db, geofence_id, current_user.organization_id
    )

    geofence.is_active = False
    geofence.updated_at = datetime.utcnow()

    db.add(geofence)
    db.commit()

    kafka_payload = _build_delete_event_payload(
        geofence_id=geofence.id,
        organization_id=current_user.organization_id,
    )
    _publish_geofence_event(
        geofences_kafka_producer,
        kafka_payload,
        endpoint="delete_geofence",
        geofence_id=geofence.id,
        organization_id=current_user.organization_id,
    )

    return GeofenceDeleteOut(
        message="Geocerca desactivada exitosamente",
        geofence_id=geofence.id,
        is_active=False,
    )

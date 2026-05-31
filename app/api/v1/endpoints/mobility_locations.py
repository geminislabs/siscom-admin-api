from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_mobility_kafka_producer
from app.schemas.mobility_location import (
    MobilityLocationIn,
    MobilityLocationOut,
    to_utc_iso_z,
)
from app.services.messaging.kafka_producer import MobilityKafkaProducer

router = APIRouter()


@router.post(
    "", response_model=MobilityLocationOut, status_code=status.HTTP_202_ACCEPTED
)
def publish_mobility_location(
    payload: MobilityLocationIn,
    mobility_kafka_producer: MobilityKafkaProducer = Depends(
        get_mobility_kafka_producer
    ),
):
    """Valida y publica una ubicación de movilidad enriquecida con received_at."""
    received_at = datetime.now(timezone.utc)
    message = {
        "device_id": str(payload.device_id),
        "recorded_at": to_utc_iso_z(payload.recorded_at),
        "received_at": to_utc_iso_z(received_at),
        "lat": payload.lat,
        "lon": payload.lon,
        "accuracy_m": payload.accuracy_m,
        "speed_mps": payload.speed_mps,
        "heading": payload.heading,
        "altitude_m": payload.altitude_m,
        "battery_level": payload.battery_level,
    }

    published = mobility_kafka_producer.publish_location(
        payload=message,
        key=str(payload.device_id),
    )
    if not published:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible publicar la ubicación en Kafka.",
        )

    return MobilityLocationOut(**message)

"""El sobre de los eventos de `control-plane-events` (ADR-008).

Lo usa `app/services/messaging/control_plane.py`, que es quien los emite.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)


def to_utc_iso_z(value: datetime | None) -> str:
    dt = value or utcnow()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def _as_str(value: UUID | str | None) -> str | None:
    if value is None:
        return None
    return str(value)


def build_control_event(
    event_type: str,
    entity: str,
    organization_id: UUID | None,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "entity": entity,
        "timestamp": to_utc_iso_z(utcnow()),
        "organization_id": _as_str(organization_id),
        "data": data,
    }

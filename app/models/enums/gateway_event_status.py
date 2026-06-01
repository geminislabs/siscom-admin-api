from __future__ import annotations

import enum


class GatewayEventStatus(str, enum.Enum):
    PROCESSED = "processed"
    FAILED = "failed"
    SKIPPED = "skipped"

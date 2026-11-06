from typing import Literal, Optional

from pydantic import BaseModel


class ClientConfigResponse(BaseModel):
    """Qué tiene que hacer la app con su versión, y adónde mandar al usuario."""

    update: Literal["none", "optional", "required"]
    latest_version: Optional[str] = None
    min_supported_version: Optional[str] = None
    store_url: Optional[str] = None

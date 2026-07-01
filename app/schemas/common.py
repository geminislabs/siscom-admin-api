"""
Schemas comunes reutilizables para respuestas de API.

Provee envelopes genéricos {data, meta} para respuestas consistentes.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PageMeta(BaseModel):
    """Metadatos de paginación."""

    page: int
    page_size: int
    total: int


class DataResponse(BaseModel, Generic[T]):
    """Envelope genérico para respuestas con un solo objeto."""

    data: T


class PaginatedResponse(BaseModel, Generic[T]):
    """Envelope genérico para respuestas paginadas."""

    data: list[T]
    meta: PageMeta

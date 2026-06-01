import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.api_platform.models.api_key import ApiKey
from app.api.v1.endpoints.api_platform.repositories.keys import ApiKeyRepository
from app.api.v1.endpoints.api_platform.schemas.keys import ApiKeyCreate, ApiKeyUpdate


def _generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, key_hash)."""
    random_part = secrets.token_urlsafe(32)
    full_key = f"orion_live_{random_part}"
    prefix = full_key[:20]
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, prefix, key_hash


class ApiKeyService:
    @staticmethod
    def create(
        db: Session, organization_id: UUID, data: ApiKeyCreate
    ) -> tuple[ApiKey, str]:
        """Create a new API key. Returns (model, full_plaintext_key)."""
        product_id = ApiKeyRepository.get_product_id_by_code(db, data.product_code)
        if product_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "product_not_found",
                    "message": "The specified product does not exist or is not available.",
                },
            )

        full_key, prefix, key_hash = _generate_api_key()

        key = ApiKey(
            id=uuid4(),
            organization_id=organization_id,
            product_id=product_id,
            name=data.name,
            key_hash=key_hash,
            prefix=prefix,
            status="ACTIVE",
            expires_at=data.expires_at,
            key_metadata=data.key_metadata,
        )
        saved = ApiKeyRepository.create(db, key)
        return saved, full_key

    @staticmethod
    def get(db: Session, key_id: UUID, organization_id: UUID) -> ApiKey:
        key = ApiKeyRepository.get_by_id(db, key_id, organization_id)
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
            )
        return key

    @staticmethod
    def list(
        db: Session,
        organization_id: UUID,
        status_filter: Optional[str] = None,
        product_code: Optional[str] = None,
    ) -> list[ApiKey]:
        product_id: Optional[UUID] = None
        if product_code is not None:
            product_id = ApiKeyRepository.get_product_id_by_code(db, product_code)
            if product_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": "product_not_found",
                        "message": "The specified product does not exist or is not available.",
                    },
                )
        return ApiKeyRepository.list_by_org(
            db, organization_id, status=status_filter, product_id=product_id
        )

    @staticmethod
    def revoke(db: Session, key_id: UUID, organization_id: UUID) -> ApiKey:
        key = ApiKeyRepository.get_by_id(db, key_id, organization_id)
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
            )
        if key.status == "REVOKED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="API key is already revoked",
            )
        key.status = "REVOKED"
        key.revoked_at = datetime.now(tz=timezone.utc)
        return ApiKeyRepository.update(db, key)

    @staticmethod
    def update(
        db: Session, key_id: UUID, organization_id: UUID, data: ApiKeyUpdate
    ) -> ApiKey:
        key = ApiKeyRepository.get_by_id(db, key_id, organization_id)
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
            )
        if data.name is not None:
            key.name = data.name
        if data.status is not None:
            key.status = data.status
        return ApiKeyRepository.update(db, key)

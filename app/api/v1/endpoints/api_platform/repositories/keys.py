from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.v1.endpoints.api_platform.models.api_key import ApiKey
from app.models.product import Product


class ApiKeyRepository:
    @staticmethod
    def create(db: Session, key: ApiKey) -> ApiKey:
        db.add(key)
        db.commit()
        db.refresh(key)
        return key

    @staticmethod
    def get_by_id(db: Session, key_id: UUID, organization_id: UUID) -> Optional[ApiKey]:
        return (
            db.query(ApiKey)
            .filter(ApiKey.id == key_id, ApiKey.organization_id == organization_id)
            .first()
        )

    @staticmethod
    def get_by_hash(db: Session, key_hash: str) -> Optional[ApiKey]:
        return db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()

    @staticmethod
    def list_by_org(
        db: Session,
        organization_id: UUID,
        status: Optional[str] = None,
        product_id: Optional[UUID] = None,
    ) -> list[ApiKey]:
        q = db.query(ApiKey).filter(ApiKey.organization_id == organization_id)
        if status:
            q = q.filter(ApiKey.status == status)
        if product_id:
            q = q.filter(ApiKey.product_id == product_id)
        return q.order_by(ApiKey.created_at.desc()).all()

    @staticmethod
    def update(db: Session, key: ApiKey) -> ApiKey:
        db.add(key)
        db.commit()
        db.refresh(key)
        return key

    @staticmethod
    def get_product_id_by_code(db: Session, code: str) -> Optional[UUID]:
        result = db.query(Product.id).filter(Product.code == code).first()
        return result[0] if result else None

    @staticmethod
    def count_active(db: Session, organization_id: UUID) -> int:
        return (
            db.query(ApiKey)
            .filter(
                ApiKey.organization_id == organization_id,
                ApiKey.status == "ACTIVE",
            )
            .count()
        )

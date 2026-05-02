from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id
from app.api.v1.endpoints.api_platform.schemas.keys import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ApiKeyUpdate,
)
from app.api.v1.endpoints.api_platform.services.keys import ApiKeyService
from app.db.session import get_db

router = APIRouter()


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    data: ApiKeyCreate,
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    key, full_key = ApiKeyService.create(db, org_id, data)
    return ApiKeyCreated(
        **ApiKeyOut.model_validate(key).model_dump(),
        full_key=full_key,
    )


@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(
    status: Optional[str] = Query(None, pattern="^(ACTIVE|REVOKED|EXPIRED)$"),
    product_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return ApiKeyService.list(db, org_id, status_filter=status, product_code=product_code)


@router.get("/{key_id}", response_model=ApiKeyOut)
def get_api_key(
    key_id: UUID,
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return ApiKeyService.get(db, key_id, org_id)


@router.post("/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_api_key(
    key_id: UUID,
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return ApiKeyService.revoke(db, key_id, org_id)


@router.patch("/{key_id}", response_model=ApiKeyOut)
def update_api_key(
    key_id: UUID,
    data: ApiKeyUpdate,
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return ApiKeyService.update(db, key_id, org_id, data)

"""
API Internal de Productos.

Endpoints para gestión completa de productos.
Uso exclusivo de GAC (staff) con autenticación PASETO.

ENDPOINTS:
- GET /internal/products - Listar todos los productos
- POST /internal/products - Crear un nuevo producto
- GET /internal/products/{product_id} - Obtener un producto específico
- PATCH /internal/products/{product_id} - Actualizar un producto
- DELETE /internal/products/{product_id} - Desactivar un producto (soft delete)

NOTA: DELETE solo cambia is_active a false, no elimina físicamente.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_solo_servicio
from app.db.session import get_db
from app.models.product import Product
from app.schemas.product import (
    ProductCreate,
    ProductOut,
    ProductsListOut,
    ProductUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Dependencia para autenticación PASETO (o Cognito para flexibilidad)
get_auth_for_internal_products = get_auth_solo_servicio(
    required_service="gac",
    required_role="GAC_ADMIN",
)


# =============================================================================
# Helpers
# =============================================================================


def _get_product_or_404(db: Session, product_id: UUID) -> Product:
    """Obtiene un producto por ID o lanza 404."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID '{product_id}' no encontrado",
        )
    return product


# =============================================================================
# Endpoints CRUD
# =============================================================================


@router.get("", response_model=ProductsListOut)
def list_products(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_products),
    search: Optional[str] = Query(
        None, description="Buscar por código o nombre (parcial, case-insensitive)"
    ),
    is_active: Optional[bool] = Query(None, description="Filtrar por estado activo"),
    limit: int = Query(50, ge=1, le=200, description="Límite de resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
):
    """
    Lista todos los productos del sistema.

    Soporta filtros por búsqueda y estado activo.
    """
    query = db.query(Product)

    # Filtro de búsqueda
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Product.code.ilike(search_filter)) | (Product.name.ilike(search_filter))
        )

    # Filtro por estado activo
    if is_active is not None:
        query = query.filter(Product.is_active == is_active)

    # Ordenar por nombre
    query = query.order_by(Product.name)

    # Paginación
    total = query.count()
    products = query.offset(offset).limit(limit).all()

    return ProductsListOut(products=products, total=total)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_products),
):
    """
    Crea un nuevo producto.

    El código debe ser único en el sistema.
    """
    try:
        # Crear el producto
        product = Product(
            code=product_in.code,
            name=product_in.name,
            description=product_in.description,
            is_active=product_in.is_active,
        )

        db.add(product)
        db.commit()
        db.refresh(product)

        logger.info(f"Producto creado: {product.id} - {product.code}")
        return product

    except IntegrityError as e:
        db.rollback()
        if "products_code_key" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El código '{product_in.code}' ya existe",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al crear el producto",
        )


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_products),
):
    """
    Obtiene un producto específico por ID.
    """
    return _get_product_or_404(db, product_id)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: UUID,
    product_in: ProductUpdate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_products),
):
    """
    Actualiza un producto existente.

    Solo actualiza los campos proporcionados (parcial).
    """
    product = _get_product_or_404(db, product_id)

    # Actualizar solo los campos proporcionados
    update_data = product_in.model_dump(exclude_unset=True)
    if not update_data:
        # Si no hay campos para actualizar, retornar el producto actual
        return product

    try:
        for field, value in update_data.items():
            setattr(product, field, value)

        db.commit()
        db.refresh(product)

        logger.info(f"Producto actualizado: {product.id} - {product.code}")
        return product

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar el producto",
        )


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_products),
):
    """
    Desactiva un producto (soft delete).

    Cambia is_active a false. No elimina físicamente el registro.
    """
    product = _get_product_or_404(db, product_id)

    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El producto ya está desactivado",
        )

    try:
        product.is_active = False
        db.commit()

        logger.info(f"Producto desactivado: {product.id} - {product.code}")

    except Exception as e:
        db.rollback()
        logger.error(f"Error al desactivar producto {product_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al desactivar el producto",
        )

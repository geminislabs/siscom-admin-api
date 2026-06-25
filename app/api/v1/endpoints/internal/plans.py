"""
API Internal de Planes.

Endpoints para gestión completa de planes, capabilities y productos.
Uso exclusivo de GAC (staff) con autenticación PASETO.

ENDPOINTS PRINCIPALES (Compuestos):
- POST /internal/plans - Crear plan completo
- PATCH /internal/plans/{plan_id} - Actualizar plan completo
- GET /internal/plans - Listar todos los planes
- GET /internal/plans/{plan_id} - Obtener un plan
- DELETE /internal/plans/{plan_id} - Eliminar plan

ENDPOINTS AUXILIARES (Uso avanzado):
- Gestión individual de capabilities
- Gestión individual de productos
- CRUD de catálogo de productos

NOTA: Los endpoints principales soportan operaciones atómicas.
La UI de GAC debe usar estos endpoints para crear/editar planes
en una sola llamada.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_cognito_or_paseto
from app.db.session import get_db
from app.models.capability import Capability, PlanCapability
from app.models.plan import Plan
from app.models.product import PlanProduct, Product
from app.models.subscription import Subscription, SubscriptionStatus
from app.schemas.plan import (
    PlanAdminOut,
    PlanCapabilitiesListOut,
    PlanCapabilityAdminOut,
    PlanCapabilityInput,
    PlanCapabilityOut,
    PlanCreate,
    PlanProductAdminOut,
    PlanProductsListOut,
    PlanUpdate,
    ProductCreate,
    ProductOut,
    ProductsListOut,
    ProductUpdate,
)
from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Helpers
# =============================================================================


def _get_plan_or_404(db: Session, plan_id: UUID) -> Plan:
    """Obtiene un plan por ID o lanza 404."""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan con ID '{plan_id}' no encontrado",
        )
    return plan


def _get_product_or_404(db: Session, product_id: UUID) -> Product:
    """Obtiene un producto por ID o lanza 404."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con ID '{product_id}' no encontrado",
        )
    return product


def _get_capability_or_404(db: Session, code: str) -> Capability:
    """Obtiene una capability por código o lanza 404."""
    capability = db.query(Capability).filter(Capability.code == code).first()
    if not capability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{code}' no encontrada",
        )
    return capability


def _get_active_subscriptions_count(db: Session, plan_id: UUID) -> int:
    """Cuenta suscripciones activas de un plan."""
    return (
        db.query(Subscription)
        .filter(
            Subscription.plan_id == plan_id,
            Subscription.status.in_(
                [
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.TRIAL.value,
                ]
            ),
        )
        .count()
    )


def _plan_to_admin_out(db: Session, plan: Plan) -> PlanAdminOut:
    """Convierte un Plan a PlanAdminOut con toda la información."""
    # Obtener capabilities
    plan_caps = (
        db.query(PlanCapability, Capability)
        .join(Capability, PlanCapability.capability_id == Capability.id)
        .filter(PlanCapability.plan_id == plan.id)
        .all()
    )

    capabilities = []
    for pc, cap in plan_caps:
        capabilities.append(
            PlanCapabilityAdminOut(
                capability_id=cap.id,
                capability_code=cap.code,
                value=pc.get_value(),
                value_type=cap.value_type,
            )
        )

    # Obtener productos
    plan_prods = (
        db.query(Product)
        .join(PlanProduct, PlanProduct.product_id == Product.id)
        .filter(PlanProduct.plan_id == plan.id)
        .all()
    )

    products = []
    for prod in plan_prods:
        products.append(
            PlanProductAdminOut(
                product_id=prod.id,
                code=prod.code,
                name=prod.name,
            )
        )

    return PlanAdminOut(
        id=plan.id,
        name=plan.name,
        code=plan.code,
        description=plan.description,
        price_monthly=plan.price_monthly,
        price_yearly=plan.price_yearly,
        is_active=plan.is_active,
        capabilities=capabilities,
        products=products,
        subscriptions_count=_get_active_subscriptions_count(db, plan.id),
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _sync_plan_capabilities(
    db: Session,
    plan: Plan,
    capabilities: list[PlanCapabilityInput],
) -> None:
    """
    Sincroniza las capabilities de un plan.

    Elimina todas las existentes y crea las nuevas.
    Operación atómica dentro de la transacción actual.
    """
    # Eliminar capabilities existentes
    db.query(PlanCapability).filter(PlanCapability.plan_id == plan.id).delete()

    # Agregar nuevas
    for cap_input in capabilities:
        capability = _get_capability_or_404(db, cap_input.capability_code)

        plan_cap = PlanCapability(
            plan_id=plan.id,
            capability_id=capability.id,
            value_int=cap_input.value_int,
            value_bool=cap_input.value_bool,
            value_text=cap_input.value_text,
            created_at=utcnow(),
        )
        db.add(plan_cap)


def _sync_plan_products(
    db: Session,
    plan: Plan,
    product_codes: list[str],
) -> None:
    """
    Sincroniza los productos de un plan.

    Elimina todos los existentes y crea los nuevos.
    Operación atómica dentro de la transacción actual.
    """
    # Eliminar productos existentes
    db.query(PlanProduct).filter(PlanProduct.plan_id == plan.id).delete()

    # Agregar nuevos
    for product_code in product_codes:
        product = db.query(Product).filter(Product.code == product_code).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto '{product_code}' no encontrado",
            )

        plan_product = PlanProduct(
            plan_id=plan.id,
            product_id=product.id,
        )
        db.add(plan_product)


# =============================================================================
# ENDPOINTS PRINCIPALES - Planes (Operaciones Compuestas)
# =============================================================================


@router.get(
    "",
    response_model=list[PlanAdminOut],
    summary="Listar planes",
    description="Lista todos los planes con información administrativa completa.",
)
def list_plans(
    include_inactive: bool = Query(
        True, description="Incluir planes inactivos (por defecto: True)"
    ),
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Lista todos los planes con información administrativa.

    Incluye:
    - Información comercial
    - Capabilities configuradas
    - Productos asociados
    - Conteo de suscripciones activas

    Por defecto incluye planes inactivos.
    """
    query = db.query(Plan)

    if not include_inactive:
        query = query.filter(Plan.is_active)

    plans = query.order_by(Plan.created_at.desc()).all()
    return [_plan_to_admin_out(db, plan) for plan in plans]


@router.post(
    "",
    response_model=PlanAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear plan completo",
    description="Crea un plan con toda su información en una sola operación.",
)
def create_plan(
    data: PlanCreate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Crea un nuevo plan con toda su configuración.

    Esta operación es atómica y crea:
    - El plan con sus datos comerciales
    - Las capabilities base del plan
    - Las asociaciones con productos

    Si alguna parte falla, se hace rollback completo.
    """
    # Verificar que el código no exista
    existing = db.query(Plan).filter(Plan.code == data.code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un plan con código '{data.code}'",
        )

    # Verificar que el nombre no exista
    existing_name = db.query(Plan).filter(Plan.name == data.name).first()
    if existing_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un plan con nombre '{data.name}'",
        )

    try:
        # Crear el plan
        plan = Plan(
            name=data.name,
            code=data.code,
            description=data.description,
            price_monthly=data.price_monthly,
            price_yearly=data.price_yearly,
            is_active=data.is_active,
        )
        db.add(plan)
        db.flush()

        # Agregar capabilities
        if data.capabilities:
            _sync_plan_capabilities(db, plan, data.capabilities)

        # Agregar productos
        if data.product_codes:
            _sync_plan_products(db, plan, data.product_codes)

        db.commit()
        db.refresh(plan)

        logger.info(
            f"[PLAN CREATE] Plan '{data.code}' creado por servicio '{auth.service}'"
        )

        return _plan_to_admin_out(db, plan)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[PLAN CREATE ERROR] {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al crear el plan",
        )


@router.patch(
    "/{plan_id}",
    response_model=PlanAdminOut,
    summary="Actualizar plan completo",
    description="Actualiza un plan con toda su información en una sola operación.",
)
def update_plan(
    plan_id: UUID,
    data: PlanUpdate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Actualiza un plan con toda su configuración.

    Esta operación es atómica y soporta edición parcial:
    - Solo se actualizan los campos enviados
    - Si se envían capabilities, se reemplazan todas
    - Si se envían products, se reemplazan todos

    Si alguna parte falla, se hace rollback completo.
    """
    plan = _get_plan_or_404(db, plan_id)

    try:
        update_data = data.model_dump(exclude_unset=True)

        # Separar campos de relación
        capabilities = update_data.pop("capabilities", None)
        product_codes = update_data.pop("product_codes", None)

        # Verificar nombre único si se está actualizando
        if "name" in update_data and update_data["name"] != plan.name:
            existing = db.query(Plan).filter(Plan.name == update_data["name"]).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Ya existe un plan con nombre '{update_data['name']}'",
                )

        # Actualizar campos del plan
        for field, value in update_data.items():
            setattr(plan, field, value)

        plan.updated_at = utcnow()

        # Sincronizar capabilities si se enviaron
        if capabilities is not None:
            cap_inputs = [PlanCapabilityInput(**cap) for cap in capabilities]
            _sync_plan_capabilities(db, plan, cap_inputs)

        # Sincronizar productos si se enviaron
        if product_codes is not None:
            _sync_plan_products(db, plan, product_codes)

        db.commit()
        db.refresh(plan)

        logger.info(
            f"[PLAN UPDATE] Plan '{plan.code}' actualizado por servicio '{auth.service}'"
        )

        return _plan_to_admin_out(db, plan)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[PLAN UPDATE ERROR] {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar el plan",
        )


@router.delete(
    "/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar plan",
    description="Elimina un plan si no tiene suscripciones activas.",
)
def delete_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Elimina un plan.

    No se puede eliminar si tiene suscripciones activas.
    Las capabilities y productos asociados se eliminan automáticamente (CASCADE).
    """
    plan = _get_plan_or_404(db, plan_id)

    # Verificar que no tenga suscripciones activas
    active_subs = _get_active_subscriptions_count(db, plan_id)
    if active_subs > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede eliminar el plan: tiene {active_subs} suscripciones activas. "
            "Considere desactivarlo en su lugar.",
        )

    # Eliminar capabilities del plan
    db.query(PlanCapability).filter(PlanCapability.plan_id == plan_id).delete()

    # Eliminar productos del plan
    db.query(PlanProduct).filter(PlanProduct.plan_id == plan_id).delete()

    # Eliminar el plan
    db.delete(plan)
    db.commit()

    logger.info(
        f"[PLAN DELETE] Plan '{plan.code}' eliminado por servicio '{auth.service}'"
    )

    return None


# =============================================================================
# ENDPOINTS AUXILIARES - Plan Capabilities (Uso avanzado)
# =============================================================================


@router.get(
    "/{plan_id}/capabilities",
    response_model=PlanCapabilitiesListOut,
    summary="Listar capabilities de un plan",
)
def list_plan_capabilities(
    plan_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Lista todas las capabilities de un plan.

    Uso: Consulta detallada para verificación o debugging.
    Para edición completa, usar PATCH /plans/{plan_id}.
    """
    plan = _get_plan_or_404(db, plan_id)

    plan_caps = (
        db.query(PlanCapability, Capability)
        .join(Capability, PlanCapability.capability_id == Capability.id)
        .filter(PlanCapability.plan_id == plan_id)
        .all()
    )

    capabilities = []
    for pc, cap in plan_caps:
        capabilities.append(
            PlanCapabilityOut(
                plan_id=plan_id,
                capability_id=cap.id,
                capability_code=cap.code,
                value=pc.get_value(),
                value_type=cap.value_type,
                created_at=pc.created_at,
            )
        )

    return PlanCapabilitiesListOut(
        plan_id=plan_id,
        plan_code=plan.code,
        capabilities=capabilities,
        total=len(capabilities),
    )


@router.post(
    "/{plan_id}/capabilities/{capability_code}",
    response_model=PlanCapabilityOut,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar capability a un plan",
)
def add_plan_capability(
    plan_id: UUID,
    capability_code: str,
    data: PlanCapabilityInput,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Agrega o actualiza una capability individual en un plan.

    Uso: Ajustes puntuales o automatizaciones.
    Para edición completa, usar PATCH /plans/{plan_id}.
    """
    plan = _get_plan_or_404(db, plan_id)
    capability = _get_capability_or_404(db, capability_code)

    # Buscar si ya existe
    existing = (
        db.query(PlanCapability)
        .filter(
            PlanCapability.plan_id == plan_id,
            PlanCapability.capability_id == capability.id,
        )
        .first()
    )

    if existing:
        # Actualizar
        existing.value_int = data.value_int
        existing.value_bool = data.value_bool
        existing.value_text = data.value_text
        db.commit()
        db.refresh(existing)
        plan_cap = existing
    else:
        # Crear
        plan_cap = PlanCapability(
            plan_id=plan_id,
            capability_id=capability.id,
            value_int=data.value_int,
            value_bool=data.value_bool,
            value_text=data.value_text,
            created_at=utcnow(),
        )
        db.add(plan_cap)
        db.commit()
        db.refresh(plan_cap)

    logger.info(
        f"[PLAN CAP] Plan '{plan.code}' capability '{capability_code}' modificada"
    )

    return PlanCapabilityOut(
        plan_id=plan_id,
        capability_id=capability.id,
        capability_code=capability.code,
        value=plan_cap.get_value(),
        value_type=capability.value_type,
        created_at=plan_cap.created_at,
    )


@router.delete(
    "/{plan_id}/capabilities/{capability_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar capability de un plan",
)
def remove_plan_capability(
    plan_id: UUID,
    capability_code: str,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Elimina una capability de un plan.

    Uso: Ajustes puntuales o automatizaciones.
    Para edición completa, usar PATCH /plans/{plan_id}.
    """
    plan = _get_plan_or_404(db, plan_id)
    capability = _get_capability_or_404(db, capability_code)

    plan_cap = (
        db.query(PlanCapability)
        .filter(
            PlanCapability.plan_id == plan_id,
            PlanCapability.capability_id == capability.id,
        )
        .first()
    )

    if not plan_cap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{capability_code}' no encontrada en el plan",
        )

    db.delete(plan_cap)
    db.commit()

    logger.info(
        f"[PLAN CAP DELETE] Plan '{plan.code}' capability '{capability_code}' eliminada"
    )

    return None


# =============================================================================
# ENDPOINTS AUXILIARES - Plan Products (Uso avanzado)
# =============================================================================


@router.get(
    "/{plan_id}/products",
    response_model=PlanProductsListOut,
    summary="Listar productos de un plan",
)
def list_plan_products(
    plan_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Lista todos los productos de un plan.

    Uso: Consulta detallada para verificación o debugging.
    Para edición completa, usar PATCH /plans/{plan_id}.
    """
    plan = _get_plan_or_404(db, plan_id)

    products = (
        db.query(Product)
        .join(PlanProduct, PlanProduct.product_id == Product.id)
        .filter(PlanProduct.plan_id == plan_id)
        .all()
    )

    return PlanProductsListOut(
        plan_id=plan_id,
        plan_code=plan.code,
        products=[ProductOut.model_validate(p) for p in products],
        total=len(products),
    )


@router.post(
    "/{plan_id}/products/{product_code}",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar producto a un plan",
)
def add_product_to_plan(
    plan_id: UUID,
    product_code: str,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Agrega un producto a un plan.

    Uso: Ajustes puntuales o automatizaciones.
    Para edición completa, usar PATCH /plans/{plan_id}.
    """
    plan = _get_plan_or_404(db, plan_id)

    product = db.query(Product).filter(Product.code == product_code).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto '{product_code}' no encontrado",
        )

    # Verificar que no exista ya
    existing = (
        db.query(PlanProduct)
        .filter(
            PlanProduct.plan_id == plan_id,
            PlanProduct.product_id == product.id,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El producto '{product_code}' ya está en el plan",
        )

    plan_product = PlanProduct(
        plan_id=plan_id,
        product_id=product.id,
    )
    db.add(plan_product)
    db.commit()

    logger.info(
        f"[PLAN PRODUCT ADD] Plan '{plan.code}' producto '{product_code}' agregado"
    )

    return ProductOut.model_validate(product)


@router.delete(
    "/{plan_id}/products/{product_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar producto de un plan",
)
def remove_product_from_plan(
    plan_id: UUID,
    product_code: str,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Elimina un producto de un plan.

    Uso: Ajustes puntuales o automatizaciones.
    Para edición completa, usar PATCH /plans/{plan_id}.
    """
    plan = _get_plan_or_404(db, plan_id)

    product = db.query(Product).filter(Product.code == product_code).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto '{product_code}' no encontrado",
        )

    plan_product = (
        db.query(PlanProduct)
        .filter(
            PlanProduct.plan_id == plan_id,
            PlanProduct.product_id == product.id,
        )
        .first()
    )

    if not plan_product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El producto '{product_code}' no está en el plan",
        )

    db.delete(plan_product)
    db.commit()

    logger.info(
        f"[PLAN PRODUCT DELETE] Plan '{plan.code}' producto '{product_code}' eliminado"
    )

    return None


# =============================================================================
# ENDPOINTS - Catálogo de Productos
# =============================================================================


@router.get(
    "/products",
    response_model=ProductsListOut,
    summary="Listar productos",
)
def list_products(
    include_inactive: bool = Query(False, description="Incluir productos inactivos"),
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Lista todos los productos disponibles.

    Por defecto solo muestra productos activos.
    """
    query = db.query(Product)

    if not include_inactive:
        query = query.filter(Product.is_active)

    products = query.order_by(Product.created_at.desc()).all()

    return ProductsListOut(
        products=[ProductOut.model_validate(p) for p in products],
        total=len(products),
    )


@router.post(
    "/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear producto",
)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Crea un nuevo producto en el catálogo.
    """
    # Verificar que el código no exista
    existing = db.query(Product).filter(Product.code == data.code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un producto con código '{data.code}'",
        )

    product = Product(
        code=data.code,
        name=data.name,
        description=data.description,
        is_active=data.is_active,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    logger.info(f"[PRODUCT CREATE] Producto '{data.code}' creado")

    return ProductOut.model_validate(product)


@router.get(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Obtener producto",
)
def get_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Obtiene un producto por ID.
    """
    product = _get_product_or_404(db, product_id)
    return ProductOut.model_validate(product)


@router.patch(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Actualizar producto",
)
def update_product(
    product_id: UUID,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Actualiza un producto.
    """
    product = _get_product_or_404(db, product_id)

    update_data = data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)

    logger.info(f"[PRODUCT UPDATE] Producto '{product.code}' actualizado")

    return ProductOut.model_validate(product)


@router.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar producto",
)
def delete_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Elimina un producto.

    No se puede eliminar si está asociado a planes.
    """
    product = _get_product_or_404(db, product_id)

    # Verificar que no esté en planes
    in_plans = (
        db.query(PlanProduct).filter(PlanProduct.product_id == product_id).count()
    )
    if in_plans > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede eliminar: el producto está asociado a {in_plans} planes",
        )

    db.delete(product)
    db.commit()

    logger.info(f"[PRODUCT DELETE] Producto '{product.code}' eliminado")

    return None


# =============================================================================
# ENDPOINTS - Catálogo de Capabilities (Read-only)
# =============================================================================


@router.get(
    "/capabilities",
    response_model=list[dict],
    summary="Listar capabilities disponibles",
)
def list_capabilities(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Lista todas las capabilities disponibles en el sistema.

    Útil para:
    - Poblar selectores en la UI
    - Conocer los tipos de valor esperados
    - Documentar las capabilities existentes
    """
    capabilities = db.query(Capability).order_by(Capability.code).all()

    return [
        {
            "id": str(cap.id),
            "code": cap.code,
            "description": cap.description,
            "value_type": cap.value_type,
        }
        for cap in capabilities
    ]


# =============================================================================
# ENDPOINTS CON PARÁMETROS - Planes individuales
# =============================================================================
# Estas rutas van DESPUÉS de las rutas específicas para evitar conflictos


@router.get(
    "/{plan_id}",
    response_model=PlanAdminOut,
    summary="Obtener plan",
    description="Obtiene un plan por ID con información administrativa completa.",
)
def get_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_cognito_or_paseto(required_service="gac")),
):
    """
    Obtiene un plan con toda su información administrativa.
    """
    plan = _get_plan_or_404(db, plan_id)
    return _plan_to_admin_out(db, plan)

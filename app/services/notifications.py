"""
Servicio de notificaciones por email usando AWS SES.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import UUID

import boto3
from botocore.exceptions import ClientError
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tenancy import TenantBranding
from app.services.tenancy import resolver_dominio_publico_de_account

logger = logging.getLogger(__name__)

# Configurar Jinja2 para cargar los templates
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# Cliente de AWS SES
ses_region = settings.SES_REGION or settings.COGNITO_REGION
ses_client_kwargs = {"region_name": ses_region}
if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
    ses_client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    ses_client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
if getattr(settings, "SES_ENDPOINT", None):
    ses_client_kwargs["endpoint_url"] = settings.SES_ENDPOINT
ses_client = boto3.client("ses", **ses_client_kwargs)


@dataclass
class BrandEmailContext:
    """
    Lo que un correo transaccional necesita saber de la marca del destinatario.

    `tagline` es `None` salvo para la marca por defecto: una marca blanca no
    tiene el lema de Geminis, y mostrarlo sería tan incorrecto como mostrar su
    logo.
    """

    brand_name: str
    logo_url: Optional[str]
    support_email: Optional[str]
    legal_url: Optional[str]
    tagline: Optional[str]
    base_url: str


_DEFAULT_BRAND = BrandEmailContext(
    brand_name="Geminis Labs",
    logo_url=None,
    support_email=None,
    legal_url=None,
    tagline="Tecnología humana y conectada",
    base_url=settings.FRONTEND_URL,
)


def _resolver_contexto_de_marca(
    db: Session, brand_account_id: Optional[UUID]
) -> BrandEmailContext:
    """
    El contexto de marca para renderizar un correo (B4).

    `brand_account_id is None` es el caso de hoy en producción —cero
    `tenant_domains` verificados— así que cae a `_DEFAULT_BRAND` sin tocar la
    base. Con una marca resuelta pero sin `TenantBranding` o sin dominio
    verificado, cada campo cae a su valor por defecto individualmente: mismo
    criterio de "marca por defecto nunca es error" que el resto de B3.
    """
    if brand_account_id is None:
        return _DEFAULT_BRAND

    branding = (
        db.query(TenantBranding)
        .filter(TenantBranding.account_id == brand_account_id)
        .first()
    )
    published = (branding.published if branding else {}) or {}
    hostname = resolver_dominio_publico_de_account(brand_account_id, db)

    return BrandEmailContext(
        brand_name=(
            branding.brand_name
            if branding and branding.brand_name
            else _DEFAULT_BRAND.brand_name
        ),
        logo_url=published.get("logo_url"),
        support_email=published.get("support_email"),
        legal_url=published.get("legal_url"),
        tagline=None,
        base_url=f"https://{hostname}" if hostname else _DEFAULT_BRAND.base_url,
    )


def _send_email(
    to: str,
    subject: str,
    html_body: str,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """
    Envía un correo electrónico usando AWS SES.

    Args:
        to: Email del destinatario
        subject: Asunto del correo
        html_body: Contenido HTML del correo
        sender_name: Nombre visible del remitente (B4); no requiere verificar
            un dominio SES por marca, solo cambia el `From` que se muestra
        reply_to: Correo de soporte de la marca, si lo tiene configurado

    Returns:
        True si se envió correctamente, False en caso de error
    """
    try:
        kwargs: dict = {
            "Source": (
                f"{sender_name} <{settings.SES_FROM_EMAIL}>"
                if sender_name
                else settings.SES_FROM_EMAIL
            ),
            "Destination": {"ToAddresses": [to]},
            "Message": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            },
        }
        if reply_to:
            kwargs["ReplyToAddresses"] = [reply_to]

        response = ses_client.send_email(**kwargs)

        logger.info(
            "notification.email.sent",
            extra={"message_id": response.get("MessageId")},
        )
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        logger.warning(
            "notification.email.client_error",
            extra={"error_code": error_code},
        )
        return False
    except Exception:
        logger.exception("notification.email.unexpected_error")
        return False


def send_verification_email(
    to: str,
    token: str,
    db: Session,
    brand_account_id: Optional[UUID] = None,
) -> bool:
    """
    Envía un correo de verificación de email.

    Args:
        to: Email del destinatario
        token: Token de verificación
        db: Sesión de base de datos, para resolver la marca (B4)
        brand_account_id: Cuenta de marca del usuario (`User.brand_account_id`),
            o `None` para la marca por defecto

    Returns:
        True si se envió correctamente
    """
    from datetime import datetime

    ctx = _resolver_contexto_de_marca(db, brand_account_id)
    action_url = f"{ctx.base_url}/verify-email?token={token}"

    template = jinja_env.get_template("verification_email.html")
    html_body = template.render(
        subject="Verifica tu correo electrónico",
        title=f"¡Bienvenido a {ctx.brand_name}!",
        message="Por favor verifica tu correo electrónico haciendo clic en el siguiente botón para activar tu cuenta.",
        action_url=action_url,
        year=datetime.now().year,
        brand_name=ctx.brand_name,
        logo_url=ctx.logo_url,
        tagline=ctx.tagline,
        legal_url=ctx.legal_url,
    )

    return _send_email(
        to=to,
        subject=f"Verifica tu correo electrónico - {ctx.brand_name}",
        html_body=html_body,
        sender_name=ctx.brand_name,
        reply_to=ctx.support_email,
    )


def send_invitation_email(
    to: str,
    token: str,
    full_name: Optional[str],
    db: Session,
    brand_account_id: Optional[UUID] = None,
) -> bool:
    """
    Envía un correo de invitación a un nuevo usuario.

    Args:
        to: Email del destinatario
        token: Token de invitación
        full_name: Nombre completo del invitado (opcional)
        db: Sesión de base de datos, para resolver la marca (B4)
        brand_account_id: Marca de quien invita (`current_user.brand_account_id`),
            no la del `Host` de la petición — quien invita ya está autenticado

    Returns:
        True si se envió correctamente
    """
    from datetime import datetime

    ctx = _resolver_contexto_de_marca(db, brand_account_id)
    action_url = f"{ctx.base_url}/accept-invitation?token={token}"

    greeting = f"¡Hola {full_name}!" if full_name else "¡Hola!"

    template = jinja_env.get_template("invitation.html")
    html_body = template.render(
        subject=f"Invitación a {ctx.brand_name}",
        title=greeting,
        message=f"Has sido invitado a unirte a {ctx.brand_name}. Haz clic en el siguiente botón para aceptar la invitación y crear tu cuenta.",
        action_url=action_url,
        year=datetime.now().year,
        brand_name=ctx.brand_name,
        logo_url=ctx.logo_url,
        tagline=ctx.tagline,
        legal_url=ctx.legal_url,
    )

    return _send_email(
        to=to,
        subject=f"Invitación a {ctx.brand_name}",
        html_body=html_body,
        sender_name=ctx.brand_name,
        reply_to=ctx.support_email,
    )


def send_password_reset_email(
    to: str,
    code: str,
    db: Session,
    brand_account_id: Optional[UUID] = None,
) -> bool:
    """
    Envía un correo de restablecimiento de contraseña con código de 6 dígitos.

    Args:
        to: Email del destinatario
        code: Código de verificación de 6 dígitos
        db: Sesión de base de datos, para resolver la marca (B4)
        brand_account_id: Cuenta de marca del usuario (`User.brand_account_id`),
            o `None` para la marca por defecto

    Returns:
        True si se envió correctamente
    """
    from datetime import datetime

    ctx = _resolver_contexto_de_marca(db, brand_account_id)

    template = jinja_env.get_template("password_reset.html")
    html_body = template.render(
        subject="Restablece tu contraseña",
        title="Restablecimiento de contraseña",
        message="Has solicitado restablecer tu contraseña. Utiliza el siguiente código de verificación en la aplicación para crear una nueva contraseña.",
        verification_code=code,
        year=datetime.now().year,
        brand_name=ctx.brand_name,
        logo_url=ctx.logo_url,
        tagline=ctx.tagline,
        legal_url=ctx.legal_url,
    )

    return _send_email(
        to=to,
        subject=f"Restablece tu contraseña - {ctx.brand_name}",
        html_body=html_body,
        sender_name=ctx.brand_name,
        reply_to=ctx.support_email,
    )


def send_sms(to: str, message: str) -> bool:
    """
    Envía un SMS (stub).

    Args:
        to: Número de teléfono del destinatario
        message: Mensaje a enviar

    Returns:
        True si se envió correctamente
    """
    # TODO: Implementar envío de SMS (Twilio, AWS SNS, etc.)
    logger.info("notification.sms.stub")
    return True


def send_push_notification(
    user_id: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> bool:
    """
    Envía una notificación push (stub).

    Args:
        user_id: ID del usuario destinatario
        title: Título de la notificación
        body: Cuerpo de la notificación
        data: Datos adicionales (opcional)

    Returns:
        True si se envió correctamente
    """
    # TODO: Implementar push notifications (Firebase, OneSignal, etc.)
    logger.info(
        "notification.push.stub",
        extra={"user_id": user_id},
    )
    return True


def send_contact_email(
    nombre: str,
    correo_electronico: Optional[str],
    telefono: Optional[str],
    mensaje: str,
) -> bool:
    """
    Envía un correo electrónico con un mensaje de contacto.

    Args:
        nombre: Nombre de la persona que envía el mensaje
        correo_electronico: Email de contacto (opcional)
        telefono: Teléfono de contacto (opcional)
        mensaje: Contenido del mensaje

    Returns:
        True si se envió correctamente, False en caso de error
    """
    from datetime import datetime

    template = jinja_env.get_template("contact_message.html")
    html_body = template.render(
        nombre=nombre,
        correo_electronico=correo_electronico or "No proporcionado",
        telefono=telefono or "No proporcionado",
        mensaje=mensaje,
        year=datetime.now().year,
    )

    return _send_email(
        to=settings.CONTACT_EMAIL,
        subject=f"Nuevo mensaje de contacto desde la página web - {nombre}",
        html_body=html_body,
    )

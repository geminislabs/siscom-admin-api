"""
Servicio de notificaciones por email usando AWS SES.
"""

from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from jinja2 import Environment, FileSystemLoader

from app.core.config import settings

# Configurar Jinja2 para cargar los templates
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# Cliente de AWS SES
ses_region = settings.SES_REGION or settings.COGNITO_REGION
ses_client_kwargs = {"region_name": ses_region}
if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
    ses_client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    ses_client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
ses_client = boto3.client("ses", **ses_client_kwargs)


def _send_email(to: str, subject: str, html_body: str) -> bool:
    """
    Envía un correo electrónico usando AWS SES.

    Args:
        to: Email del destinatario
        subject: Asunto del correo
        html_body: Contenido HTML del correo

    Returns:
        True si se envió correctamente, False en caso de error
    """
    try:
        response = ses_client.send_email(
            Source=settings.SES_FROM_EMAIL,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            },
        )

        print(f"[EMAIL] Correo enviado a {to} - MessageId: {response['MessageId']}")
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        print(
            f"[EMAIL ERROR] No se pudo enviar correo a {to}: [{error_code}] {error_message}"
        )
        return False
    except Exception as e:
        print(f"[EMAIL ERROR] Error inesperado al enviar correo a {to}: {str(e)}")
        return False


def send_verification_email(to: str, token: str) -> bool:
    """
    Envía un correo de verificación de email.

    Args:
        to: Email del destinatario
        token: Token de verificación

    Returns:
        True si se envió correctamente
    """
    from datetime import datetime

    action_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"

    template = jinja_env.get_template("verification_email.html")
    html_body = template.render(
        subject="Verifica tu correo electrónico",
        title="¡Bienvenido a SISCOM!",
        message="Por favor verifica tu correo electrónico haciendo clic en el siguiente botón para activar tu cuenta.",
        action_url=action_url,
        year=datetime.now().year,
    )

    return _send_email(
        to=to, subject="Verifica tu correo electrónico - SISCOM", html_body=html_body
    )


def send_invitation_email(to: str, token: str, full_name: Optional[str] = None) -> bool:
    """
    Envía un correo de invitación a un nuevo usuario.

    Args:
        to: Email del destinatario
        token: Token de invitación
        full_name: Nombre completo del invitado (opcional)

    Returns:
        True si se envió correctamente
    """
    from datetime import datetime

    action_url = f"{settings.FRONTEND_URL}/accept-invitation?token={token}"

    greeting = f"¡Hola {full_name}!" if full_name else "¡Hola!"

    template = jinja_env.get_template("invitation.html")
    html_body = template.render(
        subject="Invitación a SISCOM",
        title=greeting,
        message="Has sido invitado a unirte a SISCOM. Haz clic en el siguiente botón para aceptar la invitación y crear tu cuenta.",
        action_url=action_url,
        year=datetime.now().year,
    )

    return _send_email(to=to, subject="Invitación a SISCOM", html_body=html_body)


def send_password_reset_email(to: str, code: str) -> bool:
    """
    Envía un correo de restablecimiento de contraseña con código de 6 dígitos.

    Args:
        to: Email del destinatario
        code: Código de verificación de 6 dígitos

    Returns:
        True si se envió correctamente
    """
    from datetime import datetime

    template = jinja_env.get_template("password_reset.html")
    html_body = template.render(
        subject="Restablece tu contraseña",
        title="Restablecimiento de contraseña",
        message="Has solicitado restablecer tu contraseña. Utiliza el siguiente código de verificación en la aplicación para crear una nueva contraseña.",
        verification_code=code,
        year=datetime.now().year,
    )

    return _send_email(
        to=to, subject="Restablece tu contraseña - SISCOM", html_body=html_body
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
    print(f"[STUB] SMS enviado a {to}: {message}")
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
    print(f"[STUB] Push notification enviada a {user_id}: {title}")
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

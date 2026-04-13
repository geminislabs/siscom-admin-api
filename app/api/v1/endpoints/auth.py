import base64
import hashlib
import hmac
import logging
import random
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full
from app.core.config import settings
from app.db.session import get_db
from app.models.account import Account, AccountStatus
from app.models.account_user import AccountRole, AccountUser
from app.models.organization import Organization, OrganizationStatus
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.token_confirmacion import TokenConfirmacion, TokenType
from app.models.user import User
from app.schemas.account import (
    AccountOut,
    AuthMeResponse,
    OnboardingRequest,
    OnboardingResponse,
)
from app.schemas.user import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    ConfirmEmailResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    InternalTokenRequest,
    InternalTokenResponse,
    LogoutResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    UserLogin,
    UserLoginResponse,
)
from app.services.notifications import (
    send_password_reset_email,
    send_verification_email,
)
from app.utils.paseto_token import generate_service_token
from app.utils.security import generate_temporary_password, generate_verification_token

logger = logging.getLogger(__name__)

router = APIRouter()

# ------------------------------------------
# Cognito client
# ------------------------------------------
cognito_client_kwargs = {"region_name": settings.COGNITO_REGION}
if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
    cognito_client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    cognito_client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
cognito = boto3.client("cognito-idp", **cognito_client_kwargs)

# Security bearer para obtener el token
security = HTTPBearer()


def get_secret_hash(username: str) -> str:
    """
    Genera el SECRET_HASH requerido por Cognito cuando se usa CLIENT_SECRET.
    """
    message = bytes(username + settings.COGNITO_CLIENT_ID, "utf-8")
    secret = bytes(settings.COGNITO_CLIENT_SECRET, "utf-8")
    dig = hmac.new(secret, msg=message, digestmod=hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


# ------------------------------------------
# Registro de usuario (Onboarding)
# ------------------------------------------
@router.post(
    "/register", response_model=OnboardingResponse, status_code=status.HTTP_201_CREATED
)
def register_user(data: OnboardingRequest, db: Session = Depends(get_db)):
    """
    Registro rápido - Crea Account + Organization + User.

    Este endpoint representa el alta inicial de una cuenta, NO el perfil completo.
    Soporta onboarding progresivo para personas, familias y empresas.

    FLUJO:
    ======
    1. Validar que el email NO exista en users
    2. Crear Account (raíz comercial)
    3. Crear Organization default (raíz operativa)
    4. Crear User master
    5. Crear membership OWNER en organization_users
    6. Crear membership OWNER en account_users
    7. Registrar usuario en Cognito
    8. Enviar email de verificación

    Returns:
        OnboardingResponse con account_id, organization_id, user_id
    """

    # 1️⃣ ÚNICA VALIDACIÓN: Email debe ser único
    existing_user = db.query(User).filter(User.email == data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un usuario con este correo electrónico.",
        )

    # 2️⃣ Crear Account (raíz comercial)
    account = Account(
        name=data.account_name,
        billing_email=data.billing_email or data.email,
        country=data.country,
        timezone=data.timezone or "UTC",
        status=AccountStatus.ACTIVE,
    )
    db.add(account)
    db.flush()

    # 3️⃣ Crear Organization default
    org_name = (
        data.organization_name if data.organization_name else f"ORG {data.account_name}"
    )

    organization = Organization(
        account_id=account.id,
        name=org_name,
        billing_email=data.billing_email or data.email,
        country=data.country,
        timezone=data.timezone or "UTC",
        status=OrganizationStatus.ACTIVE,
    )
    db.add(organization)
    db.flush()

    # 4️⃣ Crear User master
    user_full_name = data.name if data.name else data.account_name

    user = User(
        organization_id=organization.id,
        email=data.email,
        full_name=user_full_name,
        is_master=True,
        email_verified=False,
    )
    db.add(user)
    db.flush()

    # 5️⃣ Crear membership OWNER en organization_users
    membership = OrganizationUser(
        organization_id=organization.id,
        user_id=user.id,
        role=OrganizationRole.OWNER,
    )
    db.add(membership)
    db.flush()

    # 6️⃣ Crear membership OWNER en account_users
    account_membership = AccountUser(
        account_id=account.id,
        user_id=user.id,
        role=AccountRole.OWNER.value,
    )
    db.add(account_membership)
    db.flush()

    # 8️⃣ Registrar usuario en Cognito
    cognito_sub = None
    try:
        cognito_response = cognito.admin_create_user(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=data.email,
            UserAttributes=[
                {"Name": "email", "Value": data.email},
                {"Name": "email_verified", "Value": "false"},
                {"Name": "name", "Value": user_full_name},
            ],
            MessageAction="SUPPRESS",
        )

        cognito_sub = next(
            (
                attr["Value"]
                for attr in cognito_response["User"]["Attributes"]
                if attr["Name"] == "sub"
            ),
            None,
        )

        cognito.admin_set_user_password(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=data.email,
            Password=data.password,
            Permanent=True,
        )

        if cognito_sub:
            user.cognito_sub = cognito_sub

        logger.info(f"[REGISTER] Usuario registrado en Cognito: {data.email}")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"].get("Message", str(e))

        logger.error(
            f"[REGISTER ERROR] Cognito: {error_code} - {error_message} - Email: {data.email}"
        )

        if error_code == "UsernameExistsException":
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El usuario con email {data.email} ya existe. Si es tu cuenta y no puedes acceder, contacta soporte.",
            )
        else:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo completar el registro. Por favor, intenta nuevamente o contacta soporte.",
            )

    # 9️⃣ Generar token y enviar email de verificación
    verification_token_str = generate_verification_token()
    token = TokenConfirmacion(
        token=verification_token_str,
        user_id=user.id,
        type=TokenType.EMAIL_VERIFICATION,
        password_temp=data.password,
    )
    db.add(token)

    db.commit()
    db.refresh(account)
    db.refresh(organization)
    db.refresh(user)

    # Enviar email de verificación (NO falla el endpoint si falla)
    try:
        email_sent = send_verification_email(data.email, verification_token_str)
        if email_sent:
            logger.info(f"[REGISTER] Email de verificación enviado a: {data.email}")
        else:
            logger.warning(
                f"[REGISTER] No se pudo enviar email de verificación a: {data.email}"
            )
    except Exception as e:
        logger.warning(f"[REGISTER] Error enviando email de verificación: {e}")

    return OnboardingResponse(
        account_id=account.id,
        organization_id=organization.id,
        user_id=user.id,
    )


# ------------------------------------------
# Obtener mi cuenta (Account)
# ------------------------------------------
def _get_account_for_user(db: Session, user: User) -> Account:
    """
    Obtiene el Account asociado al usuario a través de su organización.
    """
    organization = (
        db.query(Organization).filter(Organization.id == user.organization_id).first()
    )
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )

    account = db.query(Account).filter(Account.id == organization.account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account no encontrado",
        )

    return account


@router.get("/me", response_model=AuthMeResponse)
def get_my_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Obtiene el Account del usuario autenticado junto con su rol.

    Resuelve el Account a través de la organización del usuario.
    Incluye el rol del usuario en su organización actual.
    """
    account = _get_account_for_user(db, current_user)

    # Obtener el rol del usuario en su organización
    membership = (
        db.query(OrganizationUser)
        .filter(
            OrganizationUser.user_id == current_user.id,
            OrganizationUser.organization_id == current_user.organization_id,
        )
        .first()
    )

    # El rol puede ser un enum o un string dependiendo de cómo se guardó
    if membership:
        role = (
            membership.role.value
            if hasattr(membership.role, "value")
            else membership.role
        )
    else:
        role = "member"

    return AuthMeResponse(
        account=AccountOut.model_validate(account),
        role=role,
        organization_id=current_user.organization_id,
    )


# ------------------------------------------
# Login de usuario
# ------------------------------------------
@router.post("/login", response_model=UserLoginResponse, status_code=status.HTTP_200_OK)
def login_user(credentials: UserLogin, db: Session = Depends(get_db)):
    """
    Autentica un usuario con sus credenciales.

    Proceso:
    1. Verifica que el usuario exista en la base de datos
    2. Verifica que el email esté verificado
    3. Autentica con AWS Cognito
    4. Actualiza el last_login_at
    5. Retorna la información del usuario y los tokens de Cognito

    Códigos de error:
    - 404: Usuario no encontrado
    - 403: Email no verificado
    - 401: Credenciales inválidas
    """

    # 1️⃣ Buscar el usuario en la base de datos
    user = db.query(User).filter(User.email == credentials.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado"
        )

    # 2️⃣ Verificar que el email esté verificado
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Email no verificado"
        )

    # 3️⃣ Autenticar con AWS Cognito
    try:
        auth_params = {
            "USERNAME": credentials.email,
            "PASSWORD": credentials.password,
            "SECRET_HASH": get_secret_hash(credentials.email),
        }

        response = cognito.initiate_auth(
            ClientId=settings.COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters=auth_params,
        )

        # Extraer tokens de la respuesta
        auth_result = response.get("AuthenticationResult")

        if not auth_result:
            # Puede ser que requiera un challenge (ej: cambio de contraseña)
            challenge_name = response.get("ChallengeName")
            if challenge_name:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Se requiere completar el challenge: {challenge_name}",
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas",
            )

        access_token = auth_result.get("AccessToken")
        id_token = auth_result.get("IdToken")
        refresh_token = auth_result.get("RefreshToken")
        expires_in = auth_result.get("ExpiresIn", 3600)

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"].get("Message", str(e))

        # Log para debugging (en producción usar logger apropiado)
        print(
            f"[AUTH ERROR] Code: {error_code}, Message: {error_message}, Email: {credentials.email}"
        )

        if error_code == "NotAuthorizedException":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Credenciales inválidas. {error_message}",
            )
        elif error_code == "UserNotFoundException":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado en Cognito",
            )
        elif error_code == "UserNotConfirmedException":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario no confirmado en Cognito",
            )
        elif error_code == "InvalidParameterException":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error de configuración: {error_message}",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error de autenticación [{error_code}]: {error_message}",
            )

    # 4️⃣ Actualizar el last_login_at del usuario
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    # 5️⃣ Retornar la información del usuario y los tokens
    return UserLoginResponse(
        user=user,
        access_token=access_token,
        id_token=id_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=expires_in,
    )


# ------------------------------------------
# Forgot Password - Solicitud de recuperación de contraseña
# ------------------------------------------
@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
)
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Solicita la recuperación de contraseña para un usuario.

    Proceso:
    1. Verifica que el usuario exista en la base de datos
    2. Genera un código de 6 dígitos aleatorio
    3. Guarda el código en la tabla tokens_confirmacion con tipo PASSWORD_RESET
    4. Envía un correo electrónico con el código de 6 dígitos
    5. Retorna un mensaje de éxito (siempre, incluso si el email no existe, por seguridad)

    Notas de seguridad:
    - Siempre retorna el mismo mensaje, independientemente de si el usuario existe o no,
      para evitar enumerar usuarios válidos del sistema.
    """

    # 1️⃣ Buscar el usuario en la base de datos
    user = db.query(User).filter(User.email == request.email).first()

    if user:
        # 2️⃣ Generar un código de 6 dígitos aleatorio
        reset_code = str(random.randint(100000, 999999))

        # 3️⃣ Guardar el código en la base de datos
        token_record = TokenConfirmacion(
            token=reset_code,
            type=TokenType.PASSWORD_RESET,
            user_id=user.id,
            email=user.email,
            expires_at=datetime.utcnow() + timedelta(hours=1),  # Expira en 1 hora
            used=False,
        )
        db.add(token_record)
        db.commit()

        # 4️⃣ Enviar correo electrónico con el código de 6 dígitos
        email_sent = send_password_reset_email(user.email, reset_code)
        if email_sent:
            print(
                f"[PASSWORD RESET] Correo enviado a {user.email} con código: {reset_code}"
            )
        else:
            print(f"[PASSWORD RESET ERROR] No se pudo enviar el correo a {user.email}")
    else:
        # Por seguridad, no revelar que el usuario no existe
        print(
            f"[PASSWORD RESET] Intento de recuperación para email no registrado: {request.email}"
        )

    # 5️⃣ Siempre retornar el mismo mensaje de éxito (por seguridad)
    return ForgotPasswordResponse(
        message="Se ha enviado un código de verificación al correo registrado."
    )


# ------------------------------------------
# Reset Password - Restablecimiento de contraseña con código
# ------------------------------------------
@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    status_code=status.HTTP_200_OK,
)
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """
    Restablece la contraseña de un usuario utilizando un código de verificación de 6 dígitos.

    Proceso:
    1. Busca el usuario por email
    2. Busca y valida el código en la base de datos
    3. Verifica que el código no haya expirado
    4. Verifica que el código no haya sido usado
    5. Actualiza la contraseña en AWS Cognito usando AdminSetUserPassword
    6. Marca el código como usado
    7. Retorna un mensaje de éxito

    Códigos de error:
    - 400: Código inválido, expirado o ya usado
    - 404: Usuario no encontrado
    - 500: Error al actualizar la contraseña en Cognito
    """

    # 1️⃣ Buscar el usuario en la base de datos
    user = db.query(User).filter(User.email == request.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado"
        )

    # 2️⃣ Buscar el código en la base de datos
    token_record = (
        db.query(TokenConfirmacion)
        .filter(
            TokenConfirmacion.token == request.code,
            TokenConfirmacion.type == TokenType.PASSWORD_RESET,
            TokenConfirmacion.email == request.email,
        )
        .first()
    )

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código de verificación inválido",
        )

    # 3️⃣ Verificar que el código no haya expirado
    if token_record.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El código de verificación ha expirado. Por favor, solicita uno nuevo.",
        )

    # 4️⃣ Verificar que el código no haya sido usado
    if token_record.used:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este código de verificación ya ha sido utilizado",
        )

    # 5️⃣ Actualizar la contraseña en AWS Cognito
    try:
        cognito.admin_set_user_password(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=user.email,
            Password=request.new_password,
            Permanent=True,  # La contraseña es permanente, no temporal
        )

        print(f"[PASSWORD RESET] Contraseña actualizada exitosamente para {user.email}")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"].get("Message", str(e))

        print(
            f"[PASSWORD RESET ERROR] Code: {error_code}, Message: {error_message}, Email: {user.email}"
        )

        if error_code == "UserNotFoundException":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado en Cognito",
            )
        elif error_code == "InvalidPasswordException":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Contraseña inválida: {error_message}",
            )
        elif error_code == "InvalidParameterException":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Parámetro inválido: {error_message}",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al actualizar la contraseña [{error_code}]: {error_message}",
            )

    # 6️⃣ Marcar el código como usado
    token_record.used = True
    db.commit()

    # 7️⃣ Retornar mensaje de éxito
    return ResetPasswordResponse(
        message="Contraseña restablecida exitosamente. Ahora puede iniciar sesión con su nueva contraseña."
    )


# ------------------------------------------
# Change Password - Cambio de contraseña (usuario autenticado)
# ------------------------------------------
@router.patch(
    "/password", response_model=ChangePasswordResponse, status_code=status.HTTP_200_OK
)
def change_password(
    request: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Cambia la contraseña de un usuario autenticado.

    El usuario debe proporcionar su contraseña actual y la nueva contraseña.
    Utiliza ChangePassword de AWS Cognito para cambiar la contraseña de forma segura.

    Proceso:
    1. Verifica que el usuario esté autenticado
    2. Verifica que el email esté verificado
    3. Valida la contraseña actual con Cognito
    4. Cambia la contraseña usando AdminSetUserPassword
    5. Retorna mensaje de éxito

    Códigos de error:
    - 400: Contraseña actual incorrecta o nueva contraseña inválida
    - 401: Token de acceso inválido o expirado
    - 403: Email no verificado
    - 500: Error al cambiar la contraseña en Cognito

    Nota: Este endpoint requiere autenticación (Bearer token en el header Authorization)
    """

    # 0️⃣ Verificar que el email esté verificado
    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email no verificado. Debe verificar su email antes de cambiar la contraseña.",
        )

    # Para usar ChangePassword necesitamos el AccessToken del usuario
    # El access token debe venir en el header Authorization
    # Aquí tenemos un problema: get_current_user_full valida el token pero no lo retorna
    # Necesitamos obtener el access token del header

    # Por seguridad, vamos a usar AdminSetUserPassword en lugar de ChangePassword
    # Esto nos permite cambiar la contraseña sin necesitar el access token
    # Pero primero validamos la contraseña actual autenticando al usuario

    # 1️⃣ Verificar la contraseña actual autenticando con Cognito
    try:
        auth_params = {
            "USERNAME": current_user.email,
            "PASSWORD": request.old_password,
            "SECRET_HASH": get_secret_hash(current_user.email),
        }

        cognito.initiate_auth(
            ClientId=settings.COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters=auth_params,
        )

        # Si llegamos aquí, la contraseña actual es correcta

    except ClientError as e:
        error_code = e.response["Error"]["Code"]

        if error_code == "NotAuthorizedException":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La contraseña actual es incorrecta",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al verificar la contraseña actual: {error_code}",
            )

    # 2️⃣ Cambiar la contraseña usando AdminSetUserPassword
    try:
        cognito.admin_set_user_password(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=current_user.email,
            Password=request.new_password,
            Permanent=True,
        )

        print(
            f"[CHANGE PASSWORD] Contraseña actualizada exitosamente para {current_user.email}"
        )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"].get("Message", str(e))

        print(
            f"[CHANGE PASSWORD ERROR] Code: {error_code}, Message: {error_message}, Email: {current_user.email}"
        )

        if error_code == "InvalidPasswordException":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La nueva contraseña no cumple con los requisitos: {error_message}",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al actualizar la contraseña: {error_code}",
            )

    # 3️⃣ Retornar mensaje de éxito
    return ChangePasswordResponse(message="Contraseña actualizada exitosamente.")


# ------------------------------------------
# Resend Verification - Reenviar verificación de email
# ------------------------------------------
@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    status_code=status.HTTP_200_OK,
)
def resend_verification(
    request: ResendVerificationRequest, db: Session = Depends(get_db)
):
    """
    Reenvía el correo de verificación de email a un usuario no verificado.

    Proceso:
    1. Busca el usuario por email
    2. Si no existe o ya está verificado, retorna mensaje genérico (seguridad)
    3. Si existe y no está verificado:
       a. Invalida todos los tokens de verificación anteriores no usados
       b. Genera un nuevo token UUID
       c. Si es usuario master: genera password_temp para Cognito
       d. Si no es master: genera token sin password_temp
       e. Guarda el token en tokens_confirmacion con tipo EMAIL_VERIFICATION
       f. Envía el correo de verificación
    4. Retorna mensaje genérico

    Notas de seguridad:
    - Siempre retorna el mismo mensaje, sin revelar si el usuario existe o ya está verificado
    - Invalida tokens anteriores para evitar que se usen tokens antiguos
    """
    # 1️⃣ Buscar el usuario en la base de datos
    user = db.query(User).filter(User.email == request.email).first()

    # 2️⃣ Si no existe o ya está verificado, retornar mensaje genérico
    if not user:
        print(
            f"[RESEND VERIFICATION] Intento para email no registrado: {request.email}"
        )
        return ResendVerificationResponse(
            message="Si la cuenta existe, se ha reenviado el correo de verificación."
        )

    if user.email_verified:
        print(f"[RESEND VERIFICATION] Usuario ya verificado: {request.email}")
        return ResendVerificationResponse(
            message="Si la cuenta existe, se ha reenviado el correo de verificación."
        )

    # 3️⃣ Usuario existe y no está verificado, continuar con el reenvío

    # a) Buscar tokens anteriores de verificación del usuario (para reutilizar password_temp si es master)
    previous_tokens = (
        db.query(TokenConfirmacion)
        .filter(
            TokenConfirmacion.user_id == user.id,
            TokenConfirmacion.type == TokenType.EMAIL_VERIFICATION,
        )
        .order_by(TokenConfirmacion.created_at.desc())
        .all()
    )

    # b) Si es usuario master, intentar reutilizar password_temp del token más reciente
    password_temp = None
    if user.is_master:
        # Buscar el password_temp del token más reciente (usado o no usado)
        for prev_token in previous_tokens:
            if prev_token.password_temp:
                password_temp = prev_token.password_temp
                print(
                    f"[RESEND VERIFICATION] Reutilizando password_temp existente para master: {user.email}"
                )
                break

        # Si no se encontró password_temp previo, generar uno nuevo (caso excepcional)
        if not password_temp:
            password_temp = generate_temporary_password()
            print(
                f"[RESEND VERIFICATION] Generando nuevo password_temp para master (no existía previo): {user.email}"
            )
    else:
        print(
            f"[RESEND VERIFICATION] Token sin password_temp para usuario normal: {user.email}"
        )

    # c) Invalidar tokens anteriores no usados del usuario
    for token in previous_tokens:
        if not token.used:
            token.used = True

    # d) Generar nuevo token UUID
    verification_token = generate_verification_token()

    # e) Guardar el token en la base de datos
    token_record = TokenConfirmacion(
        token=verification_token,
        type=TokenType.EMAIL_VERIFICATION,
        user_id=user.id,
        email=user.email,
        password_temp=password_temp,  # Reutilizado para masters, None para usuarios normales
        expires_at=datetime.utcnow() + timedelta(hours=24),  # Expira en 24 horas
        used=False,
    )
    db.add(token_record)
    db.commit()

    # f) Enviar correo electrónico con el token
    email_sent = send_verification_email(user.email, verification_token)
    if email_sent:
        print(f"[RESEND VERIFICATION] Correo enviado a {user.email}")
    else:
        print(f"[RESEND VERIFICATION ERROR] No se pudo enviar el correo a {user.email}")

    # 4️⃣ Retornar mensaje genérico
    return ResendVerificationResponse(
        message="Si la cuenta existe, se ha reenviado el correo de verificación."
    )


# ------------------------------------------
# Verify Email - Verificar email con token (unificado)
# ------------------------------------------
@router.post(
    "/verify-email",
    response_model=ConfirmEmailResponse,
    status_code=status.HTTP_200_OK,
)
def verify_email(token: str, db: Session = Depends(get_db)):
    """
    Verifica el email de un usuario utilizando un token de verificación.

    Este endpoint unificado maneja tres flujos diferentes:

    FLUJO A - Usuario master con password_temp:
        - Crea el usuario en Cognito (si no existe)
        - Establece la contraseña usando password_temp
        - Marca email_verified=True en Cognito
        - Actualiza user.cognito_sub en la base local
        - Activa el cliente (client.status = ACTIVE)
        - Marca el token como usado

    FLUJO B - Usuario master sin password_temp:
        - Error controlado indicando que el token es inválido
        - Solicita reenvío de verificación

    FLUJO C - Usuario normal (no master):
        - Marca el email como verificado en base de datos
        - NO crea usuario en Cognito (ya debe existir)
        - NO asigna contraseña
        - NO toca el cliente
        - Marca el token como usado

    Parámetros:
    - token: Token de verificación (query parameter)

    Códigos de error:
    - 400: Token inválido, expirado o ya usado
    - 404: Usuario o cliente no encontrado
    - 500: Error al configurar usuario en Cognito
    """
    # 1️⃣ Buscar el token en la base de datos
    token_record = (
        db.query(TokenConfirmacion)
        .filter(
            TokenConfirmacion.token == token,
            TokenConfirmacion.type == TokenType.EMAIL_VERIFICATION,
        )
        .first()
    )

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de verificación inválido",
        )

    # 2️⃣ Verificar que el token no haya expirado
    if token_record.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El token de verificación ha expirado. Por favor, solicita uno nuevo.",
        )

    # 3️⃣ Verificar que el token no haya sido usado
    if token_record.used:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este token de verificación ya ha sido utilizado",
        )

    # 4️⃣ Buscar el usuario asociado al token
    user = db.query(User).filter(User.id == token_record.user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado"
        )

    # 5️⃣ Si el usuario ya está verificado, retornar error amigable
    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este email ya ha sido verificado",
        )

    # ========================================
    # FLUJO C - Usuario normal (NO master)
    # ========================================
    if not user.is_master:
        # Simplemente marcar email verificado
        user.email_verified = True
        token_record.used = True
        db.commit()

        print(
            f"[VERIFY EMAIL - FLUJO C] Email verificado para usuario normal: {user.email}"
        )

        return ConfirmEmailResponse(
            message="Email verificado exitosamente. Ahora puede iniciar sesión."
        )

    # ========================================
    # Usuario ES master - validar password_temp
    # ========================================

    # FLUJO B - Usuario master sin password_temp
    if not token_record.password_temp:
        print(
            f"[VERIFY EMAIL - FLUJO B] Token sin password_temp para usuario master: {user.email}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token inválido para usuarios master. Por favor, solicita un nuevo enlace de verificación.",
        )

    # ========================================
    # FLUJO A - Usuario master con password_temp
    # ========================================

    # Buscar la organización asociada
    organization = (
        db.query(Organization).filter(Organization.id == user.organization_id).first()
    )

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organización no encontrada"
        )

    # Verificar si el usuario ya existe en Cognito
    cognito_sub = None
    user_exists = False

    try:
        # Intentar obtener el usuario de Cognito
        existing_cognito_user = cognito.admin_get_user(
            UserPoolId=settings.COGNITO_USER_POOL_ID, Username=user.email
        )
        user_exists = True

        # Obtener el cognito_sub del usuario existente
        cognito_sub = next(
            (
                attr["Value"]
                for attr in existing_cognito_user["UserAttributes"]
                if attr["Name"] == "sub"
            ),
            None,
        )

        print(
            f"[VERIFY EMAIL - FLUJO A] Usuario master ya existe en Cognito: {user.email}"
        )

    except ClientError as e:
        if e.response["Error"]["Code"] == "UserNotFoundException":
            # Usuario no existe, continuar con la creación
            user_exists = False
            print(
                f"[VERIFY EMAIL - FLUJO A] Usuario master no existe en Cognito, creando: {user.email}"
            )
        else:
            # Otro error, re-lanzarlo
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al verificar usuario en Cognito: {e.response['Error'].get('Message', str(e))}",
            )

    try:
        if not user_exists:
            # Crear usuario en Cognito con email verificado
            cognito_resp = cognito.admin_create_user(
                UserPoolId=settings.COGNITO_USER_POOL_ID,
                Username=user.email,
                UserAttributes=[
                    {"Name": "email", "Value": user.email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name", "Value": user.full_name or ""},
                ],
                MessageAction="SUPPRESS",  # No enviar correo automático de Cognito
            )

            # Obtener el cognito_sub del usuario creado
            cognito_sub = next(
                (
                    attr["Value"]
                    for attr in cognito_resp["User"]["Attributes"]
                    if attr["Name"] == "sub"
                ),
                None,
            )

            print(
                f"[VERIFY EMAIL - FLUJO A] Usuario master creado en Cognito: {user.email}"
            )

        # Establecer contraseña permanente del usuario (ya sea nuevo o existente)
        cognito.admin_set_user_password(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=user.email,
            Password=token_record.password_temp,
            Permanent=True,  # Contraseña permanente, no temporal
        )

        # Asegurarse de que el email esté verificado en Cognito
        if user_exists:
            cognito.admin_update_user_attributes(
                UserPoolId=settings.COGNITO_USER_POOL_ID,
                Username=user.email,
                UserAttributes=[
                    {"Name": "email_verified", "Value": "true"},
                ],
            )

        if not cognito_sub:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo obtener el cognito_sub del usuario",
            )

        print(
            f"[VERIFY EMAIL - FLUJO A] Contraseña establecida para master: {user.email}"
        )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"].get("Message", str(e))

        print(
            f"[VERIFY EMAIL ERROR] Code: {error_code}, Message: {error_message}, Email: {user.email}"
        )

        if error_code == "InvalidPasswordException":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Contraseña inválida: {error_message}",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al configurar usuario en Cognito [{error_code}]: {error_message}",
            )

    # Actualizar usuario en la base de datos
    user.cognito_sub = cognito_sub
    user.email_verified = True

    # Actualizar organización a ACTIVE
    organization.status = OrganizationStatus.ACTIVE

    # Marcar token como usado y limpiar contraseña temporal
    token_record.used = True
    token_record.password_temp = None  # Limpiar contraseña por seguridad

    db.commit()

    print(
        f"[VERIFY EMAIL - FLUJO A] Organización activada exitosamente: {organization.name}"
    )

    return ConfirmEmailResponse(
        message="Email verificado exitosamente. Tu cuenta ha sido activada y ahora puedes iniciar sesión."
    )


# ------------------------------------------
# Refresh Token - Renovar access token usando refresh token
# ------------------------------------------
@router.post(
    "/refresh", response_model=RefreshTokenResponse, status_code=status.HTTP_200_OK
)
def refresh_token(request: RefreshTokenRequest):
    """
    Renueva el access token y el id token usando un refresh token válido.

    Proceso:
    1. Recibe el refresh token y el email del cliente
    2. Genera el SECRET_HASH usando el email como USERNAME
    3. Llama a initiate_auth de Cognito con el flujo REFRESH_TOKEN_AUTH
    4. Retorna los nuevos access token e id token

    Notas:
    - El refresh token NO se renueva, sigue siendo el mismo
    - Solo se renuevan el access token y el id token
    - Este endpoint NO requiere autenticación (es público)
    - Se requiere el email para generar el SECRET_HASH cuando el App Client tiene Client Secret habilitado

    Códigos de error:
    - 401: Refresh token inválido, expirado o revocado
    - 400: Parámetros inválidos
    - 500: Error al renovar los tokens en Cognito
    """

    # 1️⃣ Llamar a initiate_auth con el flujo REFRESH_TOKEN_AUTH
    try:
        # Cuando el App Client tiene Client Secret habilitado,
        # debemos incluir el SECRET_HASH incluso para REFRESH_TOKEN_AUTH.
        # El SECRET_HASH se calcula usando el email como USERNAME.
        auth_params = {
            "REFRESH_TOKEN": request.refresh_token,
            "SECRET_HASH": get_secret_hash(request.email),
        }

        response = cognito.initiate_auth(
            ClientId=settings.COGNITO_CLIENT_ID,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters=auth_params,
        )

        # Extraer tokens de la respuesta
        auth_result = response.get("AuthenticationResult")

        if not auth_result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No se pudo renovar el token",
            )

        access_token = auth_result.get("AccessToken")
        id_token = auth_result.get("IdToken")
        expires_in = auth_result.get("ExpiresIn", 3600)

        print(f"[REFRESH TOKEN] Tokens renovados exitosamente para {request.email}")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"].get("Message", str(e))

        print(
            f"[REFRESH TOKEN ERROR] Code: {error_code}, Message: {error_message}, Email: {request.email}"
        )

        if error_code == "NotAuthorizedException":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Refresh token inválido o expirado: {error_message}",
            )
        elif error_code == "InvalidParameterException":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Parámetros inválidos: {error_message}",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al renovar el token [{error_code}]: {error_message}",
            )

    # 2️⃣ Retornar los nuevos tokens
    return RefreshTokenResponse(
        access_token=access_token,
        id_token=id_token,
        token_type="Bearer",
        expires_in=expires_in,
    )


# ------------------------------------------
# Logout - Cerrar sesión del usuario actual
# ------------------------------------------
@router.post("/logout", response_model=LogoutResponse, status_code=status.HTTP_200_OK)
def logout_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Cierra la sesión del usuario actual en AWS Cognito.

    Proceso:
    1. Obtiene el access token del header Authorization
    2. Llama a global_sign_out de Cognito para invalidar todas las sesiones del usuario
    3. Retorna mensaje de éxito

    Este endpoint invalida:
    - Todos los access tokens del usuario
    - Todos los ID tokens del usuario
    - El refresh token ya no podrá usarse para obtener nuevos tokens

    Códigos de error:
    - 401: Token inválido o expirado
    - 500: Error al cerrar sesión en Cognito

    Nota: Este endpoint requiere autenticación (Bearer token en el header Authorization)
    """

    # 1️⃣ Obtener el access token del header Authorization
    access_token = credentials.credentials

    # 2️⃣ Llamar a global_sign_out de Cognito
    try:
        cognito.global_sign_out(AccessToken=access_token)

        print(f"[LOGOUT] Sesión cerrada exitosamente para {current_user.email}")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"].get("Message", str(e))

        print(
            f"[LOGOUT ERROR] Code: {error_code}, Message: {error_message}, Email: {current_user.email}"
        )

        if error_code == "NotAuthorizedException":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido o expirado",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al cerrar sesión [{error_code}]: {error_message}",
            )

    # 3️⃣ Retornar mensaje de éxito
    return LogoutResponse(message="Sesión cerrada exitosamente.")


# ------------------------------------------
# Token interno PASETO para servicios
# ------------------------------------------
@router.post(
    "/internal",
    response_model=InternalTokenResponse,
    status_code=status.HTTP_200_OK,
)
def generate_internal_token(
    request: InternalTokenRequest,
):
    """
    Genera un token PASETO para autenticación de servicios internos.

    Este endpoint permite a servicios internos obtener un token PASETO
    que puede usarse para autenticarse en otros endpoints de la API.

    **Parámetros:**
    - `email`: Email del usuario que solicita el token (obligatorio)
    - `service`: Nombre del servicio (ej: "gac")
    - `role`: Rol del servicio (ej: "GAC_ADMIN")
    - `expires_in_hours`: Horas de validez del token (default: 24, max: 720)

    **Retorna:**
    - `token`: Token PASETO generado
    - `expires_at`: Fecha de expiración del token
    - `token_type`: Tipo de token (Bearer)

    **Nota:** Este endpoint debe estar protegido en producción
    mediante reglas de firewall o API Gateway.
    """
    token, expires_at = generate_service_token(
        service=request.service,
        role=request.role,
        expires_in_hours=request.expires_in_hours,
        additional_claims={"email": request.email},
    )

    return InternalTokenResponse(
        token=token,
        expires_at=expires_at,
        token_type="Bearer",
    )

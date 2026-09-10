from datetime import timedelta
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_organization_id,
    get_current_user_full,
    get_identity_provider,
)
from app.db.session import get_db
from app.models.token_confirmacion import TokenConfirmacion, TokenType
from app.models.user import User
from app.schemas.user import (
    ResendInvitationRequest,
    ResendInvitationResponse,
    UserAcceptInvitation,
    UserAcceptInvitationResponse,
    UserInvite,
    UserInviteResponse,
    UserOut,
)
from app.services.identity import ErrorDeIdentidad, IdentityProvider
from app.services.notifications import send_invitation_email
from app.utils.datetime import utcnow
from app.utils.security import generate_verification_token

router = APIRouter()


@router.get("", response_model=List[UserOut])
def list_users(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
):
    """
    Lista todos los usuarios de la organización autenticada.
    """
    users = db.query(User).filter(User.organization_id == organization_id).all()
    return users


@router.get("/me", response_model=UserOut)
def get_current_user_info(
    current_user: User = Depends(get_current_user_full),
):
    """
    Obtiene la información del usuario actualmente autenticado.
    """
    return current_user


@router.post(
    "/invite", response_model=UserInviteResponse, status_code=status.HTTP_201_CREATED
)
def invite_user(
    data: UserInvite,
    current_user: User = Depends(get_current_user_full),
    db: Session = Depends(get_db),
):
    """
    Permite a un usuario maestro invitar a un nuevo usuario.

    Flujo:
    1. Verificar que el usuario autenticado sea maestro (is_master=True)
    2. Verificar que el email no esté ya registrado en la tabla users
    3. Generar un token único en tokens_confirmacion
    4. Enviar email con la URL de invitación (TODO)
    5. Responder con confirmación y fecha de expiración
    """

    # 1️⃣ Verificar que el usuario autenticado sea maestro
    if not current_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los usuarios maestros pueden enviar invitaciones.",
        )

    # 2️⃣ Verificar que el email no esté ya registrado
    existing_user = db.query(User).filter(User.email == data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un usuario registrado con el email {data.email}.",
        )

    # 3️⃣ Verificar que no haya una invitación pendiente para este email
    existing_invitation = (
        db.query(TokenConfirmacion)
        .filter(
            TokenConfirmacion.email == data.email,
            TokenConfirmacion.type == TokenType.INVITATION,
            ~TokenConfirmacion.used,
            TokenConfirmacion.expires_at > utcnow(),
        )
        .first()
    )
    if existing_invitation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe una invitación pendiente para {data.email}.",
        )

    # 4️⃣ Generar token de invitación
    invitation_token = generate_verification_token()
    expires_at = utcnow() + timedelta(days=3)

    token_record = TokenConfirmacion(
        token=invitation_token,
        organization_id=current_user.organization_id,
        email=data.email,
        full_name=data.full_name,
        expires_at=expires_at,
        used=False,
        type=TokenType.INVITATION,
        user_id=None,  # No hay user_id todavía, se creará al aceptar
    )

    db.add(token_record)
    db.commit()

    # 5️⃣ Enviar correo con la URL de invitación
    email_sent = send_invitation_email(data.email, invitation_token, data.full_name)
    if not email_sent:
        print(f"[WARNING] No se pudo enviar el correo de invitación a {data.email}")

    return UserInviteResponse(
        detail=f"Invitación enviada a {data.email}", expires_at=expires_at
    )


@router.post(
    "/accept-invitation",
    response_model=UserAcceptInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def accept_invitation(
    data: UserAcceptInvitation,
    db: Session = Depends(get_db),
    idp: IdentityProvider = Depends(get_identity_provider),
):
    """
    Permite a un usuario invitado aceptar la invitación y crear su cuenta.

    Flujo:
    1. Buscar token en tokens_confirmacion y validar
    2. Extraer email y client_id del token
    3. Crear usuario en Cognito con email_verified=True
    4. Crear registro en la tabla users
    5. Marcar token como usado
    6. Responder con información del usuario creado
    """

    # 1️⃣ Buscar token en la tabla tokens_confirmacion
    token_record = (
        db.query(TokenConfirmacion)
        .filter(
            TokenConfirmacion.token == data.token,
            TokenConfirmacion.type == TokenType.INVITATION,
        )
        .first()
    )

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de invitación inválido.",
        )

    # 2️⃣ Validar que el token no haya sido usado
    if token_record.used:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este token ya ha sido utilizado.",
        )

    # 3️⃣ Validar que el token no esté expirado
    if token_record.expires_at < utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de invitación expirado.",
        )

    # 4️⃣ Extraer email, full_name y organization_id del token
    email = token_record.email
    full_name = token_record.full_name
    organization_id = token_record.organization_id

    if not email or not organization_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Datos de invitación incompletos.",
        )

    # 5️⃣ Verificar que el usuario no exista (doble validación)
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un usuario con el email {email}.",
        )

    # 6️⃣ ¿Existe ya la credencial en el proveedor de identidad?
    #
    # El handle de un alta nueva sigue siendo el correo, como hasta ahora. La
    # rebanada B2 lo cambia por un UUID; el único sitio que hay que tocar es
    # este, porque `external_id` se guarda en la fila unas líneas más abajo.
    handle = email

    try:
        cognito_sub = idp.sujeto_de(handle=handle)
    except ErrorDeIdentidad as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al verificar usuario en Cognito: {e.mensaje}",
        )

    user_exists = cognito_sub is not None
    if user_exists:
        print(f"[ACCEPT INVITATION] Usuario ya existe en Cognito: {email}")

    try:
        if not user_exists:
            # 7️⃣ Crear la credencial con el correo ya verificado
            cognito_sub = idp.crear_credencial(
                handle=handle,
                email=email,
                full_name=full_name or None,
                email_verificado=True,
            )

            print(f"[ACCEPT INVITATION] Usuario creado en Cognito: {email}")

        # 8️⃣ Establecer contraseña proporcionada por el usuario (permanente)
        idp.fijar_password(handle=handle, password=data.password)

        # 9️⃣ Asegurarse de que el email esté verificado en el proveedor
        if user_exists:
            idp.marcar_correo_verificado(handle=handle, email=email)

        if not cognito_sub:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo obtener el identificador de Cognito.",
            )

    except ErrorDeIdentidad as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al configurar usuario en Cognito [{e.codigo}]: {e.mensaje}",
        )

    # 9️⃣ Crear usuario en la base de datos
    new_user = User(
        email=email,
        full_name=full_name or email,  # Usar full_name del token o email como fallback
        organization_id=organization_id,
        cognito_sub=cognito_sub,
        external_id=handle,
        is_master=False,
        email_verified=True,
        # password_hash no se usa, la autenticación es con Cognito
    )

    db.add(new_user)

    # 🔟 Marcar token como usado
    token_record.used = True
    token_record.user_id = new_user.id  # Asociar el user_id creado

    db.commit()
    db.refresh(new_user)

    return UserAcceptInvitationResponse(
        detail="Usuario creado exitosamente.", user=new_user
    )


@router.post(
    "/resend-invitation",
    response_model=ResendInvitationResponse,
    status_code=status.HTTP_200_OK,
)
def resend_invitation(
    data: ResendInvitationRequest,
    current_user: User = Depends(get_current_user_full),
    db: Session = Depends(get_db),
):
    """
    Reenvía una invitación a un usuario que no ha aceptado su invitación original.

    Solo usuarios maestros pueden reenviar invitaciones.

    Flujo:
    1. Verificar que el usuario autenticado sea maestro
    2. Buscar invitación(es) existente(s) para ese email
    3. Verificar que no sea un usuario ya registrado
    4. Invalidar invitación(es) anterior(es) no usada(s)
    5. Generar nueva invitación con nuevo token y nueva expiración
    6. TODO: Enviar email con nueva URL de invitación
    7. Responder con confirmación y nueva fecha de expiración

    Códigos de error:
    - 403: Usuario no es maestro
    - 400: No existe invitación pendiente o el usuario ya está registrado
    """

    # 1️⃣ Verificar que el usuario autenticado sea maestro
    if not current_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los usuarios maestros pueden reenviar invitaciones.",
        )

    # 2️⃣ Verificar que el email NO esté ya registrado
    existing_user = db.query(User).filter(User.email == data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario {data.email} ya está registrado en el sistema.",
        )

    # 3️⃣ Buscar invitaciones existentes para este email (incluyendo expiradas)
    existing_invitations = (
        db.query(TokenConfirmacion)
        .filter(
            TokenConfirmacion.email == data.email,
            TokenConfirmacion.type == TokenType.INVITATION,
            TokenConfirmacion.organization_id == current_user.organization_id,
            ~TokenConfirmacion.used,
        )
        .all()
    )

    if not existing_invitations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No existe una invitación pendiente para {data.email} en este cliente.",
        )

    # 4️⃣ Obtener datos de la invitación original (full_name)
    original_invitation = existing_invitations[0]
    full_name = original_invitation.full_name

    # 5️⃣ Invalidar todas las invitaciones anteriores no usadas
    for invitation in existing_invitations:
        invitation.used = True

    # 6️⃣ Generar nueva invitación
    new_token = generate_verification_token()
    expires_at = utcnow() + timedelta(days=3)

    new_invitation = TokenConfirmacion(
        token=new_token,
        organization_id=current_user.organization_id,
        email=data.email,
        full_name=full_name,
        expires_at=expires_at,
        used=False,
        type=TokenType.INVITATION,
    )

    db.add(new_invitation)
    db.commit()
    db.refresh(new_invitation)

    # 7️⃣ Enviar email con la nueva URL de invitación
    email_sent = send_invitation_email(data.email, new_token, full_name)
    if email_sent:
        print(f"[RESEND INVITATION] Correo enviado a {data.email}")
    else:
        print(f"[RESEND INVITATION ERROR] No se pudo enviar el correo a {data.email}")

    return ResendInvitationResponse(
        message=f"Invitación reenviada a {data.email}", expires_at=expires_at
    )

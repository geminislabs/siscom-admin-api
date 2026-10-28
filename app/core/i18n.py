"""
Catálogo bilingüe (es / en) de mensajes de error y respuestas para la API.
"""

from typing import Any, Literal

SupportedLocale = Literal["es", "en"]

MESSAGES: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------
    # app/api/deps.py
    # ------------------------------------------------------------------
    "deps.token_missing_sub": {
        "es": "Token inválido: falta 'sub'",
        "en": "Invalid token: missing 'sub'",
    },
    "deps.cognito_token_missing_sub": {
        "es": "Token de Cognito inválido: falta 'sub'",
        "en": "Invalid Cognito token: missing 'sub'",
    },
    "deps.user_not_found_in_system": {
        "es": "Usuario no encontrado en el sistema",
        "en": "User not found in the system",
    },
    "deps.user_not_found": {
        "es": "Usuario no encontrado",
        "en": "User not found",
    },
    "deps.no_active_membership": {
        "es": "Sin membresía activa en la organización solicitada",
        "en": "No active membership in the requested organization",
    },
    "deps.service_to_service_only": {
        "es": "Esta ruta es de servicio a servicio: requiere un token PASETO válido.",
        "en": "This route is service-to-service only: a valid PASETO token is required.",
    },
    "deps.invalid_token_cognito_or_paseto": {
        "es": "Token inválido. Se requiere un token de Cognito válido o un token PASETO de servicio válido.",
        "en": "Invalid token. A valid Cognito token or a valid service PASETO token is required.",
    },
    "deps.org_permission_required": {
        "es": "Se requiere el permiso {permission} en esta organización",
        "en": "Permission {permission} is required in this organization",
    },
    "deps.org_capability_required": {
        "es": "La organización no tiene acceso a: {capability_code}",
        "en": "The organization does not have access to: {capability_code}",
    },
    "deps.account_permission_required": {
        "es": "Se requiere el permiso {permission} en esta cuenta",
        "en": "Permission {permission} is required in this account",
    },
    # ------------------------------------------------------------------
    # app/api/v1/endpoints/auth.py
    # ------------------------------------------------------------------
    "auth.user_already_exists": {
        "es": "Ya existe un usuario con este correo electrónico.",
        "en": "A user with this email address already exists.",
    },
    "auth.handle_already_exists": {
        "es": "El usuario con email {email} ya existe. Si es tu cuenta y no puedes acceder, contacta soporte.",
        "en": "A user with email {email} already exists. If this is your account and you cannot sign in, please contact support.",
    },
    "auth.register_failed": {
        "es": "No se pudo completar el registro. Por favor, intenta nuevamente o contacta soporte.",
        "en": "Registration could not be completed. Please try again or contact support.",
    },
    "auth.organization_not_found": {
        "es": "Organización no encontrada",
        "en": "Organization not found",
    },
    "auth.account_not_found": {
        "es": "Account no encontrado",
        "en": "Account not found",
    },
    "auth.user_not_found": {
        "es": "Usuario no encontrado",
        "en": "User not found",
    },
    # Invariante acordada con iOS y Android: conservar la palabra "verify" en inglés
    # porque los clientes detectan el 403 de correo no verificado buscando "verif" en detail.lower().
    "auth.email_not_verified": {
        "es": "Email no verificado",
        "en": "Please verify your email address before signing in.",
    },
    "auth.challenge_required": {
        "es": "Se requiere completar el challenge: {challenge}",
        "en": "Challenge completion required: {challenge}",
    },
    "auth.invalid_credentials": {
        "es": "Credenciales inválidas",
        "en": "Invalid credentials",
    },
    "auth.invalid_credentials_with_msg": {
        "es": "Credenciales inválidas. {message}",
        "en": "Invalid credentials. {message}",
    },
    "auth.user_not_found_cognito": {
        "es": "Usuario no encontrado en Cognito",
        "en": "User not found in Cognito",
    },
    "auth.user_not_confirmed_cognito": {
        "es": "Usuario no confirmado en Cognito",
        "en": "User not confirmed in Cognito",
    },
    "auth.config_error": {
        "es": "Error de configuración: {message}",
        "en": "Configuration error: {message}",
    },
    "auth.auth_error": {
        "es": "Error de autenticación [{code}]: {message}",
        "en": "Authentication error [{code}]: {message}",
    },
    "auth.forgot_password_sent": {
        "es": "Se ha enviado un código de verificación al correo registrado.",
        "en": "A verification code has been sent to the registered email address.",
    },
    "auth.invalid_verification_code": {
        "es": "Código de verificación inválido",
        "en": "Invalid verification code",
    },
    "auth.verification_code_expired": {
        "es": "El código de verificación ha expirado. Por favor, solicita uno nuevo.",
        "en": "The verification code has expired. Please request a new one.",
    },
    "auth.verification_code_used": {
        "es": "Este código de verificación ya ha sido utilizado",
        "en": "This verification code has already been used",
    },
    "auth.invalid_password": {
        "es": "Contraseña inválida: {message}",
        "en": "Invalid password: {message}",
    },
    "auth.invalid_parameter": {
        "es": "Parámetro inválido: {message}",
        "en": "Invalid parameter: {message}",
    },
    "auth.password_update_error": {
        "es": "Error al actualizar la contraseña [{code}]: {message}",
        "en": "Error updating password [{code}]: {message}",
    },
    "auth.password_updated_revoke_failed": {
        "es": (
            "La contraseña se actualizó, pero no se pudieron cerrar las "
            "sesiones anteriores. Cierra sesión en tus otros dispositivos."
        ),
        "en": (
            "Your password was updated, but previous sessions could not be "
            "closed. Please sign out on your other devices."
        ),
    },
    "auth.password_reset_success": {
        "es": "Contraseña restablecida exitosamente. Ahora puede iniciar sesión con su nueva contraseña.",
        "en": "Password reset successfully. You can now sign in with your new password.",
    },
    "auth.email_not_verified_change_password": {
        "es": "Email no verificado. Debe verificar su email antes de cambiar la contraseña.",
        "en": "Email not verified. Please verify your email before changing your password.",
    },
    "auth.current_password_incorrect": {
        "es": "La contraseña actual es incorrecta",
        "en": "Current password is incorrect",
    },
    "auth.verify_current_password_error": {
        "es": "Error al verificar la contraseña actual: {code}",
        "en": "Error verifying current password: {code}",
    },
    "auth.new_password_requirements": {
        "es": "La nueva contraseña no cumple con los requisitos: {message}",
        "en": "The new password does not meet the requirements: {message}",
    },
    "auth.update_password_code_error": {
        "es": "Error al actualizar la contraseña: {code}",
        "en": "Error updating password: {code}",
    },
    "auth.password_changed_success": {
        "es": "Contraseña actualizada exitosamente.",
        "en": "Password updated successfully.",
    },
    "auth.resend_verification_sent": {
        "es": "Si la cuenta existe, se ha reenviado el correo de verificación.",
        "en": "If the account exists, the verification email has been resent.",
    },
    "auth.invalid_verification_token": {
        "es": "Token de verificación inválido",
        "en": "Invalid verification token",
    },
    "auth.verification_token_expired": {
        "es": "El token de verificación ha expirado. Por favor, solicita uno nuevo.",
        "en": "The verification token has expired. Please request a new one.",
    },
    "auth.verification_token_used": {
        "es": "Este token de verificación ya ha sido utilizado",
        "en": "This verification token has already been used",
    },
    "auth.email_already_verified": {
        "es": "Este email ya ha sido verificado",
        "en": "This email has already been verified",
    },
    "auth.email_verified_member_success": {
        "es": "Email verificado exitosamente. Ahora puede iniciar sesión.",
        "en": "Email verified successfully. You can now sign in.",
    },
    "auth.master_missing_temp_password": {
        "es": "Token inválido para usuarios master. Por favor, solicita un nuevo enlace de verificación.",
        "en": "Invalid token for master users. Please request a new verification link.",
    },
    "auth.cognito_verify_user_error": {
        "es": "Error al verificar usuario en Cognito: {message}",
        "en": "Error verifying user in Cognito: {message}",
    },
    "auth.cognito_sub_missing": {
        "es": "No se pudo obtener el cognito_sub del usuario",
        "en": "Could not obtain user cognito_sub",
    },
    "auth.cognito_configure_user_error": {
        "es": "Error al configurar usuario en Cognito [{code}]: {message}",
        "en": "Error configuring user in Cognito [{code}]: {message}",
    },
    "auth.email_verified_master_success": {
        "es": "Email verificado exitosamente. Tu cuenta ha sido activada y ahora puedes iniciar sesión.",
        "en": "Email verified successfully. Your account has been activated and you can now sign in.",
    },
    "auth.missing_authorization_header": {
        "es": "Falta la cabecera Authorization",
        "en": "Missing Authorization header",
    },
    "auth.token_refresh_failed": {
        "es": "No se pudo renovar el token",
        "en": "Could not refresh token",
    },
    "auth.refresh_token_invalid": {
        "es": "Refresh token inválido o expirado: {message}",
        "en": "Invalid or expired refresh token: {message}",
    },
    "auth.invalid_parameters": {
        "es": "Parámetros inválidos: {message}",
        "en": "Invalid parameters: {message}",
    },
    "auth.too_many_refreshes": {
        "es": "Demasiadas renovaciones seguidas. Intenta de nuevo en unos segundos.",
        "en": "Too many token refresh attempts. Please try again in a few seconds.",
    },
    "auth.refresh_token_error": {
        "es": "Error al renovar el token [{code}]: {message}",
        "en": "Error refreshing token [{code}]: {message}",
    },
    "auth.token_invalid_or_expired": {
        "es": "Token inválido o expirado",
        "en": "Invalid or expired token",
    },
    "auth.logout_error": {
        "es": "Error al cerrar sesión [{code}]: {message}",
        "en": "Error signing out [{code}]: {message}",
    },
    "auth.logout_success": {
        "es": "Sesión cerrada exitosamente.",
        "en": "Signed out successfully.",
    },
    "auth.data_service_unavailable": {
        "es": "El servicio de datos no está disponible temporalmente",
        "en": "Data service is temporarily unavailable",
    },
    # ------------------------------------------------------------------
    # app/api/v1/endpoints/users.py
    # ------------------------------------------------------------------
    "users.invite_only_master": {
        "es": "Solo los usuarios maestros pueden enviar invitaciones.",
        "en": "Only master users can send invitations.",
    },
    "users.email_already_registered": {
        "es": "Ya existe un usuario registrado con el email {email}.",
        "en": "A user is already registered with the email {email}.",
    },
    "users.invitation_already_pending": {
        "es": "Ya existe una invitación pendiente para {email}.",
        "en": "A pending invitation already exists for {email}.",
    },
    "users.invitation_sent": {
        "es": "Invitación enviada a {email}",
        "en": "Invitation sent to {email}",
    },
    "users.invalid_invitation_token": {
        "es": "Token de invitación inválido.",
        "en": "Invalid invitation token.",
    },
    "users.invitation_token_used": {
        "es": "Este token ya ha sido utilizado.",
        "en": "This token has already been used.",
    },
    "users.invitation_token_expired": {
        "es": "Token de invitación expirado.",
        "en": "Invitation token has expired.",
    },
    "users.incomplete_invitation_data": {
        "es": "Datos de invitación incompletos.",
        "en": "Incomplete invitation data.",
    },
    "users.user_with_email_exists": {
        "es": "Ya existe un usuario con el email {email}.",
        "en": "A user with the email {email} already exists.",
    },
    "users.cognito_id_missing": {
        "es": "No se pudo obtener el identificador de Cognito.",
        "en": "Could not obtain Cognito identifier.",
    },
    "users.user_created_success": {
        "es": "Usuario creado exitosamente.",
        "en": "User created successfully.",
    },
    "users.resend_invite_only_master": {
        "es": "Solo los usuarios maestros pueden reenviar invitaciones.",
        "en": "Only master users can resend invitations.",
    },
    "users.user_already_in_system": {
        "es": "El usuario {email} ya está registrado en el sistema.",
        "en": "User {email} is already registered in the system.",
    },
    "users.no_pending_invitation": {
        "es": "No existe una invitación pendiente para {email} en este cliente.",
        "en": "No pending invitation exists for {email} in this organization.",
    },
    "users.invitation_resent": {
        "es": "Invitación reenviada a {email}",
        "en": "Invitation resent to {email}",
    },
    # ------------------------------------------------------------------
    # app/api/v1/endpoints/user_commands.py & commands.py
    # ------------------------------------------------------------------
    "user_commands.password_validation_unavailable": {
        "es": "No se pudo validar la contraseña en este momento",
        "en": "Could not validate password at this time",
    },
    "user_commands.unsupported_device_model": {
        "es": (
            "No se pudo formar el comando para el modelo del equipo. "
            "Modelo actual: brand='{brand}', model='{model}'. "
            "Actualmente se soportan modelos Suntech con patrón ST4 + 3 dígitos "
            "(ej: ST4330, ST4315, ST4315U)"
        ),
        "en": (
            "Could not build command for the device model. "
            "Current model: brand='{brand}', model='{model}'. "
            "Currently Suntech models matching ST4 + 3 digits are supported "
            "(e.g. ST4330, ST4315, ST4315U)"
        ),
    },
    "user_commands.only_master": {
        "es": "Solo el usuario master puede ejecutar este endpoint",
        "en": "Only the master user can execute this endpoint",
    },
    "user_commands.engine_stop_requires_confirmation": {
        "es": "ENGINE_STOP requiere confirmation",
        "en": "ENGINE_STOP requires confirmation",
    },
    "user_commands.engine_stop_requires_accepted_risk": {
        "es": "Debe confirmar accepted_risk=true para ENGINE_STOP",
        "en": "You must confirm accepted_risk=true for ENGINE_STOP",
    },
    "user_commands.invalid_password": {
        "es": "Contraseña inválida",
        "en": "Invalid password",
    },
    "user_commands.unit_not_found": {
        "es": "Unidad no encontrada",
        "en": "Unit not found",
    },
    "user_commands.unit_has_no_device": {
        "es": "La unidad no tiene un dispositivo asignado",
        "en": "The unit does not have an assigned device",
    },
    "user_commands.device_not_found_for_unit": {
        "es": "Dispositivo no encontrado para la unidad",
        "en": "Device not found for the unit",
    },
    "user_commands.device_has_no_kore_sim": {
        "es": "El dispositivo no tiene una SIM KORE configurada",
        "en": "The device does not have a configured KORE SIM",
    },
    "user_commands.invalid_status_filter": {
        "es": "Estado inválido. Valores válidos: pending, sent, delivered, failed",
        "en": "Invalid status. Valid values: pending, sent, delivered, failed",
    },
    "user_commands.command_not_found": {
        "es": "Comando user-command no encontrado",
        "en": "User command not found",
    },
    "commands.device_not_found": {
        "es": "Dispositivo no encontrado",
        "en": "Device not found",
    },
    "commands.cognito_token_missing_email": {
        "es": "Token Cognito inválido: falta el campo 'email'",
        "en": "Invalid Cognito token: missing 'email' field",
    },
    "commands.command_not_found": {
        "es": "Comando no encontrado",
        "en": "Command not found",
    },
    "commands.sync_not_implemented": {
        "es": (
            "Sincronización no implementada para media '{media}'. "
            "Solo se soporta 'KORE_SMS_API'"
        ),
        "en": (
            "Synchronization not implemented for media '{media}'. "
            "Only 'KORE_SMS_API' is supported"
        ),
    },
    "commands.missing_metadata": {
        "es": "El comando no tiene metadata",
        "en": "The command has no metadata",
    },
    "commands.missing_kore_response": {
        "es": "El comando no tiene kore_response en metadata",
        "en": "The command has no kore_response in metadata",
    },
    "commands.missing_sid_or_url": {
        "es": "El kore_response no contiene 'sid' o 'url'",
        "en": "kore_response does not contain 'sid' or 'url'",
    },
    # ------------------------------------------------------------------
    # app/api/v1/endpoints/alert_rules.py
    # ------------------------------------------------------------------
    "alert_rules.duplicate_message": {
        "es": "Ya existe una regla con el mismo tipo y configuracion para esta organizacion",
        "en": "A rule with the same type and configuration already exists for this organization",
    },
    "alert_rules.duplicate_detail": {
        "es": (
            "El fingerprint se genera con organization_id, type y config normalizado. "
            "Cambia el tipo o la configuracion de la regla para crear una nueva."
        ),
        "en": (
            "The fingerprint is generated from organization_id, type, and normalized config. "
            "Change the rule type or configuration to create a new one."
        ),
    },
    "alert_rules.invalid_unit_ids": {
        "es": (
            "Todas las unidades deben pertenecer a la organización del usuario "
            "y estar activas. unit_ids inválidos: {missing}"
        ),
        "en": (
            "All units must belong to the user's organization "
            "and be active. Invalid unit_ids: {missing}"
        ),
    },
    "alert_rules.not_found": {
        "es": "Regla no encontrada",
        "en": "Alert rule not found",
    },
    "alert_rules.deleted_success": {
        "es": "Regla eliminada exitosamente",
        "en": "Alert rule deleted successfully",
    },
    # ------------------------------------------------------------------
    # app/api/v1/endpoints/alerts.py
    # ------------------------------------------------------------------
    "alerts.unit_not_found": {
        "es": "Unidad no encontrada",
        "en": "Unit not found",
    },
    "alerts.unit_access_denied": {
        "es": "No tienes permiso para acceder a esta unidad",
        "en": "You do not have permission to access this unit",
    },
    # ------------------------------------------------------------------
    # app/api/v1/endpoints/geofences.py
    # ------------------------------------------------------------------
    "geofences.not_found": {
        "es": "Geocerca no encontrada",
        "en": "Geofence not found",
    },
    "geofences.create_conflict": {
        "es": "No se pudo crear la geocerca por conflicto de integridad",
        "en": "Could not create geofence due to an integrity conflict",
    },
    "geofences.update_conflict": {
        "es": "No se pudo actualizar la geocerca por conflicto de integridad",
        "en": "Could not update geofence due to an integrity conflict",
    },
    "geofences.deactivated_success": {
        "es": "Geocerca desactivada exitosamente",
        "en": "Geofence deactivated successfully",
    },
    # ------------------------------------------------------------------
    # app/api/v1/endpoints/units.py
    # ------------------------------------------------------------------
    "units.not_found": {
        "es": "Unidad no encontrada",
        "en": "Unit not found",
    },
    "units.access_denied": {
        "es": "No tienes permiso para acceder a esta unidad",
        "en": "You do not have permission to access this unit",
    },
    "units.role_required": {
        "es": "Se requiere rol '{required_role}' o superior",
        "en": "Role '{required_role}' or higher is required",
    },
    "units.only_master_can_create": {
        "es": "Solo los usuarios maestros pueden crear unidades",
        "en": "Only master users can create units",
    },
    "units.device_not_found_or_not_in_org": {
        "es": "Dispositivo no encontrado o no pertenece a tu organización",
        "en": "Device not found or does not belong to your organization",
    },
    "units.device_invalid_status": {
        "es": "El dispositivo debe estar en estado 'entregado' o 'devuelto' (estado actual: {status})",
        "en": "Device must be in 'entregado' or 'devuelto' status (current status: {status})",
    },
    "units.device_already_assigned_other": {
        "es": "El dispositivo ya está asignado a otra unidad activa",
        "en": "The device is already assigned to another active unit",
    },
    "units.only_master_can_delete": {
        "es": "Solo los usuarios maestros pueden eliminar unidades",
        "en": "Only master users can delete units",
    },
    "units.cannot_delete_with_active_devices": {
        "es": "No se puede eliminar la unidad porque tiene {count} dispositivo(s) activo(s) asignado(s)",
        "en": "Cannot delete unit because it has {count} active assigned device(s)",
    },
    "units.deleted_success": {
        "es": "Unidad eliminada exitosamente",
        "en": "Unit deleted successfully",
    },
    "units.device_already_assigned_this": {
        "es": "El dispositivo ya está asignado a esta unidad",
        "en": "The device is already assigned to this unit",
    },
    "units.assign_device_conflict": {
        "es": "Conflicto al asignar dispositivo. Intenta nuevamente.",
        "en": "Conflict assigning device. Please try again.",
    },
    "units.unit_profile_not_found": {
        "es": "El perfil de unidad no existe. Usa GET /units/{unit_id}/profile primero para crearlo.",
        "en": "Unit profile does not exist. Use GET /units/{unit_id}/profile first to create it.",
    },
    "units.vehicle_profile_only_for_vehicles": {
        "es": "El perfil de vehículo solo se puede crear para unidades de tipo 'vehicle' (tipo actual: {unit_type})",
        "en": "Vehicle profile can only be created for units of type 'vehicle' (current type: {unit_type})",
    },
    "units.vehicle_profile_already_exists": {
        "es": "Ya existe un perfil de vehículo para esta unidad. Usa PATCH para actualizarlo.",
        "en": "A vehicle profile already exists for this unit. Use PATCH to update it.",
    },
    "units.vehicle_profile_not_found": {
        "es": "El perfil de vehículo no existe. Usa POST /units/{unit_id}/profile/vehicle para crearlo.",
        "en": "Vehicle profile does not exist. Use POST /units/{unit_id}/profile/vehicle to create it.",
    },
    "units.only_master_can_assign_users": {
        "es": "Solo los usuarios maestros pueden asignar usuarios a unidades",
        "en": "Only master users can assign users to units",
    },
    "units.user_not_found_or_not_in_org": {
        "es": "Usuario no encontrado o no pertenece a tu organización",
        "en": "User not found or does not belong to your organization",
    },
    "units.cannot_assign_master_user": {
        "es": "No es necesario asignar usuarios maestros (ya tienen acceso a todas las unidades)",
        "en": "Assigning master users is not necessary (they already have access to all units)",
    },
    "units.user_already_has_access": {
        "es": "El usuario ya tiene acceso a esta unidad con rol '{role}'",
        "en": "The user already has access to this unit with role '{role}'",
    },
    "units.user_assigned_success": {
        "es": "Usuario asignado exitosamente",
        "en": "User assigned successfully",
    },
    "units.only_master_can_revoke_users": {
        "es": "Solo los usuarios maestros pueden revocar accesos a unidades",
        "en": "Only master users can revoke unit access",
    },
    "units.user_does_not_have_access": {
        "es": "El usuario no tiene acceso a esta unidad",
        "en": "The user does not have access to this unit",
    },
    "units.user_access_revoked_success": {
        "es": "Acceso revocado exitosamente",
        "en": "Access revoked successfully",
    },
    "units.no_active_device_for_share": {
        "es": "La unidad no tiene un dispositivo asignado actualmente",
        "en": "The unit does not currently have an assigned device",
    },
    "units.share_location_unavailable": {
        "es": "Compartir ubicación no está disponible temporalmente",
        "en": "Location sharing is temporarily unavailable",
    },
    # ------------------------------------------------------------------
    # app/api/v1/endpoints/user_devices.py
    # ------------------------------------------------------------------
    "user_devices.sns_registration_failed": {
        "es": (
            "No fue posible registrar el dispositivo en SNS. "
            "Verifica AWS_REGION y los ARN de plataforma SNS."
        ),
        "en": (
            "Could not register the device in SNS. "
            "Please check AWS_REGION and SNS platform ARNs."
        ),
    },
    "user_devices.not_found": {
        "es": "Dispositivo no encontrado",
        "en": "Device not found",
    },
    "user_devices.deactivated_success": {
        "es": "Dispositivo desactivado exitosamente",
        "en": "Device deactivated successfully",
    },
}


def t(key: str, locale: str = "es", **kwargs: Any) -> str:
    """
    Traduce una clave del catálogo `MESSAGES` al idioma solicitado (`es` o `en`).

    Si `locale` no es un string válido (`"es"` o `"en"`) —por ejemplo cuando una
    dependencia de FastAPI se invoca directamente en un test unitario sin resolver
    `Depends(get_request_locale)`—, cae de forma segura a `"es"`.
    """
    lang = locale if isinstance(locale, str) and locale in ("es", "en") else "es"
    entry = MESSAGES.get(key)
    if not entry:
        return key
    template = entry.get(lang) or entry.get("es") or key
    if kwargs:
        return template.format(**kwargs)
    return template

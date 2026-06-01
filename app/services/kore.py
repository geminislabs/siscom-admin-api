"""
Servicio de integración con KORE Wireless API.

Este servicio maneja la autenticación y envío de comandos SMS
a través de la API de KORE Wireless (SuperSIM).
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class KoreAuthResponse:
    """Respuesta de autenticación de KORE."""

    access_token: str
    expires_in: int
    token_type: str
    scope: str


@dataclass
class KoreSmsResponse:
    """Respuesta de envío de SMS de KORE."""

    success: bool
    message: str
    response_data: Optional[dict] = None


class KoreServiceError(Exception):
    """Excepción base para errores del servicio KORE."""

    pass


class KoreAuthError(KoreServiceError):
    """Error de autenticación con KORE."""

    pass


class KoreSmsError(KoreServiceError):
    """Error al enviar SMS a través de KORE."""

    pass


class KoreService:
    """
    Servicio para interactuar con la API de KORE Wireless.

    Proporciona métodos para:
    - Autenticación OAuth2 (client_credentials)
    - Envío de comandos SMS a dispositivos SuperSIM
    """

    def __init__(self):
        self.client_id = settings.KORE_CLIENT_ID
        self.client_secret = settings.KORE_CLIENT_SECRET
        self.api_base_url = settings.KORE_API
        self.auth_url = settings.KORE_API_AUTH
        self.sms_url = settings.KORE_API_SMS
        base_url = (self.api_base_url or "").rstrip("/")
        self.sims_url = f"{base_url}/Sims" if base_url else None
        self._cached_token: Optional[str] = None

    def is_configured(self) -> bool:
        """
        Verifica si el servicio KORE está correctamente configurado.

        Returns:
            True si todas las variables de entorno necesarias están definidas.
        """
        return all(
            [
                self.client_id,
                self.client_secret,
                self.auth_url,
                self.sms_url,
            ]
        )

    def is_sync_configured(self) -> bool:
        """
        Verifica si el servicio KORE está configurado para sincronización de SIMs.

        Returns:
            True si las variables necesarias para auth y listado de SIMs están definidas.
        """
        return all(
            [
                self.client_id,
                self.client_secret,
                self.auth_url,
                self.sims_url,
            ]
        )

    async def authenticate(self) -> KoreAuthResponse:
        """
        Obtiene un token de acceso de la API de KORE usando client_credentials.

        Returns:
            KoreAuthResponse con el access_token y metadata.

        Raises:
            KoreAuthError: Si la autenticación falla.
        """
        if not self.is_configured():
            raise KoreAuthError(
                "Servicio KORE no configurado. "
                "Verifique las variables de entorno KORE_*"
            )

        headers = {
            "cache-control": "no-cache",
            "content-type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.auth_url,
                    headers=headers,
                    data=data,
                )

                if response.status_code != 200:
                    logger.error(
                        f"[KORE AUTH] Error de autenticación: "
                        f"Status {response.status_code}, Body: {response.text}"
                    )
                    raise KoreAuthError(
                        f"Error de autenticación KORE: {response.status_code}"
                    )

                response_data = response.json()

                auth_response = KoreAuthResponse(
                    access_token=response_data["access_token"],
                    expires_in=response_data["expires_in"],
                    token_type=response_data["token_type"],
                    scope=response_data.get("scope", ""),
                )

                # Cachear el token para uso posterior
                self._cached_token = auth_response.access_token

                logger.info(
                    f"[KORE AUTH] Autenticación exitosa. "
                    f"Token expira en {auth_response.expires_in}s"
                )

                return auth_response

        except httpx.RequestError as e:
            logger.error(f"[KORE AUTH] Error de conexión: {str(e)}")
            raise KoreAuthError(f"Error de conexión con KORE: {str(e)}")
        except KeyError as e:
            logger.error(f"[KORE AUTH] Respuesta inválida, falta campo: {str(e)}")
            raise KoreAuthError(f"Respuesta de KORE inválida: falta {str(e)}")

    async def send_sms_command(
        self,
        kore_sim_id: str,
        payload: str,
        access_token: Optional[str] = None,
    ) -> KoreSmsResponse:
        """
        Envía un comando SMS a un dispositivo a través de KORE SuperSIM.

        Args:
            kore_sim_id: ID de la SIM en KORE (ej: HS0ad6bc269850dfe13bc8bddfcf8399f4)
            payload: Comando a enviar al dispositivo
            access_token: Token de acceso. Si no se proporciona, se usa el cacheado
                          o se realiza una nueva autenticación.

        Returns:
            KoreSmsResponse con el resultado del envío.

        Raises:
            KoreSmsError: Si el envío del SMS falla.
        """
        if not self.is_configured():
            raise KoreSmsError(
                "Servicio KORE no configurado. "
                "Verifique las variables de entorno KORE_*"
            )

        # Obtener token si no se proporciona
        token = access_token or self._cached_token
        if not token:
            auth_response = await self.authenticate()
            token = auth_response.access_token

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "Sim": kore_sim_id,
            "Payload": payload,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.sms_url,
                    headers=headers,
                    data=data,
                )

                response_data = None
                try:
                    response_data = response.json()
                except Exception:
                    pass

                if response.status_code in (200, 201, 202):
                    logger.info(
                        f"[KORE SMS] Comando enviado exitosamente a SIM {kore_sim_id}"
                    )
                    return KoreSmsResponse(
                        success=True,
                        message="Comando enviado exitosamente",
                        response_data=response_data,
                    )
                else:
                    logger.error(
                        f"[KORE SMS] Error al enviar comando: "
                        f"Status {response.status_code}, Body: {response.text}"
                    )
                    return KoreSmsResponse(
                        success=False,
                        message=f"Error KORE: {response.status_code}",
                        response_data=response_data,
                    )

        except httpx.RequestError as e:
            logger.error(f"[KORE SMS] Error de conexión: {str(e)}")
            raise KoreSmsError(f"Error de conexión con KORE: {str(e)}")

    async def send_command(
        self,
        kore_sim_id: str,
        command: str,
    ) -> KoreSmsResponse:
        """
        Método conveniente que realiza autenticación y envío de SMS en un solo paso.

        Args:
            kore_sim_id: ID de la SIM en KORE
            command: Comando a enviar al dispositivo

        Returns:
            KoreSmsResponse con el resultado del envío.

        Raises:
            KoreAuthError: Si la autenticación falla.
            KoreSmsError: Si el envío del SMS falla.
        """
        # Autenticar primero
        auth_response = await self.authenticate()

        # Enviar el comando
        return await self.send_sms_command(
            kore_sim_id=kore_sim_id,
            payload=command,
            access_token=auth_response.access_token,
        )

    async def list_sims(
        self,
        page_size: int = 50,
        access_token: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Lista todas las SIMs de KORE recorriendo la paginación de la API.

        Args:
            page_size: Tamaño de página solicitado a KORE.
            access_token: Token de acceso opcional. Si no se pasa, usa cache o autentica.

        Returns:
            Lista completa de objetos SIM retornados por KORE.

        Raises:
            KoreAuthError: Si falla autenticación o faltan variables de configuración.
            KoreServiceError: Si falla la consulta de SIMs.
        """
        if not self.is_sync_configured():
            raise KoreAuthError(
                "Servicio KORE no configurado para sincronización de SIMs. "
                "Verifique KORE_CLIENT_ID, KORE_CLIENT_SECRET, KORE_API_AUTH y KORE_API"
            )

        token = access_token or self._cached_token
        if not token:
            auth_response = await self.authenticate()
            token = auth_response.access_token

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        all_sims: list[dict[str, Any]] = []
        next_page_url: Optional[str] = f"{self.sims_url}?Page=0&PageSize={page_size}"
        pages_fetched = 0

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while next_page_url:
                    response = await client.get(next_page_url, headers=headers)

                    if response.status_code == 401:
                        logger.warning(
                            "[KORE SIMS] Token expirado, reintentando con autenticación nueva"
                        )
                        auth_response = await self.authenticate()
                        headers["Authorization"] = (
                            f"Bearer {auth_response.access_token}"
                        )
                        response = await client.get(next_page_url, headers=headers)

                    if response.status_code != 200:
                        logger.error(
                            f"[KORE SIMS] Error consultando SIMs: "
                            f"Status {response.status_code}, Body: {response.text}"
                        )
                        raise KoreServiceError(
                            f"Error consultando SIMs en KORE: {response.status_code}"
                        )

                    payload = response.json()
                    meta = payload.get("meta", {})
                    sims_key = meta.get("key") or "sims"
                    sims_page = payload.get(sims_key, [])

                    if not isinstance(sims_page, list):
                        logger.error(
                            "[KORE SIMS] Respuesta inválida: '%s' no es una lista",
                            sims_key,
                        )
                        raise KoreServiceError(
                            "Respuesta inválida de KORE al listar SIMs"
                        )

                    all_sims.extend(sims_page)
                    next_page_url = meta.get("next_page_url")
                    pages_fetched += 1

            logger.info(
                "[KORE SIMS] Sincronización remota completada: %s SIMs en %s páginas",
                len(all_sims),
                pages_fetched,
            )
            return all_sims

        except httpx.RequestError as e:
            logger.error(f"[KORE SIMS] Error de conexión: {str(e)}")
            raise KoreServiceError(f"Error de conexión con KORE: {str(e)}")
        except ValueError as e:
            logger.error(f"[KORE SIMS] JSON inválido en respuesta: {str(e)}")
            raise KoreServiceError("Respuesta inválida de KORE al listar SIMs")


# Instancia singleton del servicio
kore_service = KoreService()

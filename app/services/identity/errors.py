"""
Los fallos de un proveedor de identidad, dichos en el idioma del dominio.

POR QUE EXISTE ESTE MODULO
==========================
Antes de la rebanada B, cada endpoint atrapaba `botocore.exceptions.ClientError`
y leía `e.response["Error"]["Code"]` para decidir el HTTP que devolvía. Eso
significaba que la forma de una excepción de boto3 —y con ella el vocabulario de
Cognito: `NotAuthorizedException`, `UserNotFoundException`— era parte del
contrato de `/auth/login`. Cambiar de proveedor habría obligado a reescribir
cada `except`.

Aquí se traduce una vez, en el adaptador, y el resto del sistema captura estas
clases. Un proveedor nuevo implementa la interfaz y lanza lo mismo; los
endpoints no se enteran.

QUE LLEVA CADA UNA, Y QUE NO
============================
`mensaje` es texto de diagnóstico del proveedor. Se conserva porque los
endpoints lo venían devolviendo al cliente y esta rebanada es un refactor: no
cambia una sola respuesta. **No se ramifica sobre él** — para eso está la clase.
"""


class ErrorDeIdentidad(Exception):
    """Raíz de todo fallo de identidad."""

    def __init__(self, mensaje: str = "", *, codigo: str = ""):
        super().__init__(mensaje or codigo or self.__class__.__name__)
        self.mensaje = mensaje
        #: Código del proveedor. Opaco: sirve para el log y para el detalle que
        #: ya devolvían los endpoints, nunca para decidir.
        self.codigo = codigo


class CredencialesInvalidas(ErrorDeIdentidad):
    """La contraseña no corresponde al handle."""


class CredencialNoEncontrada(ErrorDeIdentidad):
    """No hay ninguna credencial con ese handle en el proveedor.

    Que exista la fila en `users` y no la credencial es un descuadre real y no
    una rareza teórica: pasa si alguien borra el usuario desde la consola del
    proveedor.
    """


class CredencialSinConfirmar(ErrorDeIdentidad):
    """La credencial existe pero el proveedor aún no la da por confirmada."""


class HandleYaExiste(ErrorDeIdentidad):
    """Ya hay una credencial con ese handle.

    Con handles UUID (rebanada B2) esto deja de significar «ese correo ya está
    tomado» y pasa a ser lo que dice: una colisión de handle.
    """


class PasswordRechazada(ErrorDeIdentidad):
    """La contraseña no cumple la política del proveedor."""


class ParametroInvalido(ErrorDeIdentidad):
    """El proveedor rechazó la llamada por su forma, no por las credenciales.

    Casi siempre es configuración del despliegue —un client id que no cuadra,
    un flujo de autenticación deshabilitado—, no culpa de quien entra.
    """


class AutenticacionIncompleta(ErrorDeIdentidad):
    """El proveedor no entregó sesión: pide un paso más antes de continuar.

    `reto` es el nombre que el proveedor le da a ese paso. Es **texto opaco**:
    se registra y se enseña en el detalle, y ningún código de dominio decide
    nada con él. El día que haya un flujo de retos de verdad, será un tipo del
    dominio y no una cadena del proveedor.
    """

    def __init__(self, mensaje: str = "", *, reto: str = "", codigo: str = ""):
        super().__init__(mensaje, codigo=codigo)
        self.reto = reto


class ErrorDelProveedor(ErrorDeIdentidad):
    """Cualquier otro fallo del proveedor. Se traduce a 500."""


class ProveedorDesconocido(ErrorDeIdentidad):
    """La cuenta pide un proveedor que este despliegue no sabe manejar.

    Es la segunda línea de defensa: `ck_accounts_identity_provider` ya impide
    escribir en la base un nombre que el código no conoce. Esta salta si el
    código va por detrás del dato —una reversión del despliegue después de
    ampliar el CHECK—, y falla ruidosamente en vez de autenticar contra el
    proveedor equivocado.
    """

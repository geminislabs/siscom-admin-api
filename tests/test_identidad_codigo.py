"""
Fase 3, rebanada B1: modelos de identidad e interfaz `IdentityProvider`.

QUE SE PRUEBA AQUI, Y SOBRE QUE
===============================
Tres cosas distintas, en este orden:

1. **Los modelos**, sobre el harness normal (Postgres, esquema por
   `create_all()`). Al declarar los índices de la 028 en `__table_args__`, la
   unicidad por marca existe también aquí y se puede ejercitar.
2. **El registro de proveedores**: quién elige y con qué se queda.
3. **El adaptador de Cognito**, con un doble en lugar del cliente de boto3. Es
   la única capa que conoce a Cognito, así que es la única donde tiene sentido
   escribir `NotAuthorizedException` en un test.

LO QUE NO SE PRUEBA AQUI
========================
El trigger `users_identidad_before` y el backfill: son de la base y los cubre
`test_identidad_esquema.py`, que levanta una base con las migraciones de
verdad. Aquí el hueco lo tapa `_handle_por_defecto`, que es la misma regla
escrita del lado de la aplicación — y que existe justamente porque este harness
no tiene triggers.
"""

import uuid

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.account import Account
from app.models.user import User
from app.services import identity
from app.services.identity import (
    AutenticacionIncompleta,
    CredencialesInvalidas,
    CredencialNoEncontrada,
    CredencialSinConfirmar,
    ErrorDelProveedor,
    HandleYaExiste,
    ParametroInvalido,
    PasswordRechazada,
    ProveedorDesconocido,
    Sesion,
)
from app.services.identity.cognito import CognitoIdentityProvider

# ─────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────


def _marca(db, nombre="Mero Mero"):
    """Una cuenta que hace de marca."""
    cuenta = Account(id=uuid.uuid4(), name=nombre, status="ACTIVE")
    db.add(cuenta)
    db.flush()
    return cuenta


def _usuario(db, org, correo, **campos):
    user = User(id=uuid.uuid4(), organization_id=org.id, email=correo, **campos)
    db.add(user)
    db.flush()
    return user


def _error_de_cognito(codigo: str, mensaje: str = "lo que diga AWS") -> ClientError:
    return ClientError(
        {"Error": {"Code": codigo, "Message": mensaje}}, "OperacionCualquiera"
    )


class _ClienteFalso:
    """Un doble del cliente de boto3 que apunta con qué se le llamó."""

    def __init__(self, **respuestas):
        self.respuestas = respuestas
        self.llamadas = []

    def __getattr__(self, nombre):
        def llamada(**kwargs):
            self.llamadas.append((nombre, kwargs))
            respuesta = self.respuestas.get(nombre, {})
            if isinstance(respuesta, Exception):
                raise respuesta
            return respuesta

        return llamada

    def kwargs_de(self, nombre):
        return next(k for n, k in self.llamadas if n == nombre)


# ─────────────────────────────────────────────────────────────────────
# Los modelos
# ─────────────────────────────────────────────────────────────────────


def test_el_handle_por_defecto_es_el_correo(db_session, test_organization_data):
    """Un alta que no trae handle nace con el correo, igual que con el trigger.

    Y el valor queda en el objeto tras el flush, no solo en la fila: el código
    que crea la credencial lo lee de ahí en la misma petición.
    """
    user = _usuario(db_session, test_organization_data, "sin-handle@example.com")

    assert user.external_id == "sin-handle@example.com"
    assert user.identity_provider == "cognito"
    assert user.brand_account_id is None


def test_un_handle_explicito_gana(db_session, test_organization_data):
    """Lo que escribe la aplicación manda: es como la B2 pondrá los UUID."""
    handle = str(uuid.uuid4())
    user = _usuario(
        db_session,
        test_organization_data,
        "con-handle@example.com",
        external_id=handle,
    )

    assert user.external_id == handle


def test_dos_marcas_pueden_compartir_correo(db_session, test_organization_data):
    """El punto entero de la fase: el correo identifica dentro de una marca."""
    una = _marca(db_session, "Mero Mero")
    otra = _marca(db_session, "Otro Partner")

    _usuario(
        db_session,
        test_organization_data,
        "misma@example.com",
        brand_account_id=una.id,
        external_id="handle-en-una",
    )
    _usuario(
        db_session,
        test_organization_data,
        "misma@example.com",
        brand_account_id=otra.id,
        external_id="handle-en-otra",
    )

    db_session.flush()  # si chocaran, aquí saltaría

    cuantos = db_session.query(User).filter(User.email == "misma@example.com").count()
    assert cuantos == 2


def test_dentro_de_una_marca_el_correo_sigue_siendo_unico(
    db_session, test_organization_data
):
    marca = _marca(db_session)
    _usuario(
        db_session,
        test_organization_data,
        "repetida@example.com",
        brand_account_id=marca.id,
        external_id="handle-1",
    )

    with pytest.raises(IntegrityError):
        _usuario(
            db_session,
            test_organization_data,
            "repetida@example.com",
            brand_account_id=marca.id,
            external_id="handle-2",
        )


def test_la_marca_por_defecto_conserva_la_unicidad_de_hoy(
    db_session, test_organization_data
):
    """Sin este índice, quitar `users_email_key` habría dejado sin unicidad de
    correo a todo el padrón actual, en silencio y el mismo día del despliegue.
    """
    _usuario(
        db_session,
        test_organization_data,
        "sin-marca@example.com",
        external_id="handle-a",
    )

    with pytest.raises(IntegrityError):
        _usuario(
            db_session,
            test_organization_data,
            "sin-marca@example.com",
            external_id="handle-b",
        )


def test_el_handle_es_unico_dentro_del_proveedor(db_session, test_organization_data):
    marca = _marca(db_session)
    _usuario(
        db_session,
        test_organization_data,
        "uno@example.com",
        external_id="el-mismo-handle",
    )

    with pytest.raises(IntegrityError):
        _usuario(
            db_session,
            test_organization_data,
            "otro@example.com",
            brand_account_id=marca.id,
            external_id="el-mismo-handle",
        )


def test_una_cuenta_nace_sin_proveedor_propio(db_session):
    """`NULL` = hereda el del despliegue, y `idp_config` es un objeto vacío."""
    cuenta = _marca(db_session, "Recién creada")
    db_session.refresh(cuenta)

    assert cuenta.identity_provider is None
    assert cuenta.idp_config == {}


# ─────────────────────────────────────────────────────────────────────
# Quién elige el proveedor
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _sin_instancias_cacheadas():
    identity.reiniciar_proveedores()
    yield
    identity.reiniciar_proveedores()


def test_una_cuenta_sin_proveedor_usa_el_del_despliegue(db_session):
    cuenta = _marca(db_session)

    assert isinstance(identity.proveedor_para_cuenta(cuenta), CognitoIdentityProvider)


def test_sin_cuenta_tambien_sale_el_del_despliegue():
    """`None` es la marca por defecto, que hoy es la de todos los usuarios."""
    assert isinstance(identity.proveedor_para_cuenta(None), CognitoIdentityProvider)


def test_un_proveedor_que_el_codigo_no_conoce_falla_ruidosamente(db_session):
    """Antes de autenticar contra el proveedor equivocado, se para.

    La cuenta se construye en memoria y no se guarda: en la base este valor lo
    frena `ck_accounts_identity_provider`. Esta es la segunda línea.
    """
    cuenta = Account(id=uuid.uuid4(), name="Enterprise", identity_provider="workos")

    with pytest.raises(ProveedorDesconocido):
        identity.proveedor_para_cuenta(cuenta)


def test_el_proveedor_se_construye_una_sola_vez():
    """El cliente de boto3 es caro de crear y seguro de compartir."""
    assert identity.proveedor_por_defecto() is identity.proveedor_por_defecto()


# ─────────────────────────────────────────────────────────────────────
# El adaptador de Cognito
# ─────────────────────────────────────────────────────────────────────


def test_autenticar_devuelve_los_tokens_ya_extraidos():
    cliente = _ClienteFalso(
        initiate_auth={
            "AuthenticationResult": {
                "AccessToken": "acceso",
                "IdToken": "id",
                "RefreshToken": "refresco",
                "ExpiresIn": 900,
            }
        }
    )

    sesion = CognitoIdentityProvider(cliente).autenticar(handle="h", password="secreta")

    assert sesion == Sesion(
        access_token="acceso",
        id_token="id",
        refresh_token="refresco",
        expires_in=900,
    )


def test_el_secret_hash_se_firma_con_el_handle_y_no_con_el_correo():
    """Firmarlo con el correo mientras se autentica con un UUID da un
    `NotAuthorizedException` indistinguible de una contraseña mal escrita. Es
    el error natural cuando lleguen los handles UUID de la rebanada B2.
    """
    import base64
    import hashlib
    import hmac

    handle = str(uuid.uuid4())
    cliente = _ClienteFalso(
        initiate_auth={"AuthenticationResult": {"AccessToken": "a"}}
    )

    CognitoIdentityProvider(cliente).autenticar(handle=handle, password="x")

    esperado = base64.b64encode(
        hmac.new(
            settings.COGNITO_CLIENT_SECRET.encode(),
            msg=(handle + settings.COGNITO_CLIENT_ID).encode(),
            digestmod=hashlib.sha256,
        ).digest()
    ).decode()
    params = cliente.kwargs_de("initiate_auth")["AuthParameters"]
    assert params["USERNAME"] == handle
    assert params["SECRET_HASH"] == esperado


def test_un_reto_pendiente_no_cruza_como_dato_de_cognito():
    """Sale una excepción del dominio; el nombre del reto viaja como texto."""
    cliente = _ClienteFalso(initiate_auth={"ChallengeName": "NEW_PASSWORD_REQUIRED"})

    with pytest.raises(AutenticacionIncompleta) as capturado:
        CognitoIdentityProvider(cliente).autenticar(handle="h", password="x")

    assert capturado.value.reto == "NEW_PASSWORD_REQUIRED"


def test_sin_sesion_y_sin_reto_son_credenciales_invalidas():
    cliente = _ClienteFalso(initiate_auth={})

    with pytest.raises(CredencialesInvalidas):
        CognitoIdentityProvider(cliente).autenticar(handle="h", password="x")


@pytest.mark.parametrize(
    "codigo, clase",
    [
        ("NotAuthorizedException", CredencialesInvalidas),
        ("UserNotFoundException", CredencialNoEncontrada),
        ("UserNotConfirmedException", CredencialSinConfirmar),
        ("UsernameExistsException", HandleYaExiste),
        ("InvalidPasswordException", PasswordRechazada),
        ("InvalidParameterException", ParametroInvalido),
        ("UnaQueNadieHaVistoException", ErrorDelProveedor),
    ],
)
def test_cada_error_de_cognito_se_traduce_al_dominio(codigo, clase):
    """El vocabulario de Cognito muere aquí: fuera solo salen estas clases."""
    cliente = _ClienteFalso(initiate_auth=_error_de_cognito(codigo))

    with pytest.raises(clase) as capturado:
        CognitoIdentityProvider(cliente).autenticar(handle="h", password="x")

    assert capturado.value.codigo == codigo
    assert capturado.value.mensaje == "lo que diga AWS"


def test_una_credencial_que_no_existe_no_es_un_error():
    """`sujeto_de` devuelve None: los dos sitios que lo llaman deciden con eso
    si crear la credencial.
    """
    cliente = _ClienteFalso(admin_get_user=_error_de_cognito("UserNotFoundException"))

    assert CognitoIdentityProvider(cliente).sujeto_de(handle="h") is None


def test_sujeto_de_saca_el_sub_de_los_atributos():
    cliente = _ClienteFalso(
        admin_get_user={
            "UserAttributes": [
                {"Name": "email", "Value": "x@example.com"},
                {"Name": "sub", "Value": "el-sujeto"},
            ]
        }
    )

    assert CognitoIdentityProvider(cliente).sujeto_de(handle="h") == "el-sujeto"


def test_otro_fallo_al_consultar_si_es_un_error():
    """Solo «no existe» es una respuesta. Una caída no puede leerse como que
    la credencial no está, o el flujo la crearía por segunda vez.
    """
    cliente = _ClienteFalso(admin_get_user=_error_de_cognito("TooManyRequests"))

    with pytest.raises(ErrorDelProveedor):
        CognitoIdentityProvider(cliente).sujeto_de(handle="h")


def test_crear_credencial_no_manda_correo_y_devuelve_el_sujeto():
    cliente = _ClienteFalso(
        admin_create_user={"User": {"Attributes": [{"Name": "sub", "Value": "s1"}]}}
    )

    sujeto = CognitoIdentityProvider(cliente).crear_credencial(
        handle="h", email="x@example.com", full_name="Quien Sea"
    )

    kwargs = cliente.kwargs_de("admin_create_user")
    assert sujeto == "s1"
    # Cognito no envía un solo correo en este sistema: los manda SES con la
    # plantilla de la marca.
    assert kwargs["MessageAction"] == "SUPPRESS"
    assert kwargs["Username"] == "h"
    assert {"Name": "name", "Value": "Quien Sea"} in kwargs["UserAttributes"]
    assert {"Name": "email_verified", "Value": "false"} in kwargs["UserAttributes"]


def test_sin_nombre_no_se_manda_el_atributo_name():
    cliente = _ClienteFalso(admin_create_user={"User": {"Attributes": []}})

    CognitoIdentityProvider(cliente).crear_credencial(
        handle="h", email="x@example.com", email_verificado=True
    )

    kwargs = cliente.kwargs_de("admin_create_user")
    assert all(a["Name"] != "name" for a in kwargs["UserAttributes"])
    assert {"Name": "email_verified", "Value": "true"} in kwargs["UserAttributes"]


def test_marcar_verificado_manda_el_correo_junto_al_email_verified():
    """Cognito exige `email` en la misma llamada: sin él, falla."""
    cliente = _ClienteFalso()

    CognitoIdentityProvider(cliente).marcar_correo_verificado(
        handle="h", email="x@example.com"
    )

    assert cliente.kwargs_de("admin_update_user_attributes")["UserAttributes"] == [
        {"Name": "email", "Value": "x@example.com"},
        {"Name": "email_verified", "Value": "true"},
    ]


def test_fijar_password_la_deja_permanente():
    """Sin `Permanent`, la credencial queda en FORCE_CHANGE_PASSWORD y el
    siguiente login pide un reto.
    """
    cliente = _ClienteFalso()

    CognitoIdentityProvider(cliente).fijar_password(handle="h", password="nueva")

    assert cliente.kwargs_de("admin_set_user_password")["Permanent"] is True


def test_renovar_usa_el_flujo_de_refresco():
    cliente = _ClienteFalso(
        initiate_auth={"AuthenticationResult": {"AccessToken": "a", "IdToken": "i"}}
    )

    sesion = CognitoIdentityProvider(cliente).renovar(handle="h", refresh_token="r")

    kwargs = cliente.kwargs_de("initiate_auth")
    assert kwargs["AuthFlow"] == "REFRESH_TOKEN_AUTH"
    assert kwargs["AuthParameters"]["REFRESH_TOKEN"] == "r"
    # El refresco no se renueva: Cognito no lo devuelve y la sesión lo refleja.
    assert sesion.refresh_token is None
    assert sesion.expires_in == 3600


def test_revocar_sesiones_cierra_todas_las_del_token():
    cliente = _ClienteFalso()

    CognitoIdentityProvider(cliente).revocar_sesiones(access_token="acceso")

    assert cliente.kwargs_de("global_sign_out")["AccessToken"] == "acceso"


def test_verificar_token_devuelve_los_claims(monkeypatch):
    monkeypatch.setattr(
        "app.core.security.verify_cognito_token", lambda t: {"sub": "s"}
    )

    assert CognitoIdentityProvider(_ClienteFalso()).verificar_token("t") == {"sub": "s"}


@pytest.mark.parametrize(
    "codigo_http, clase",
    [
        (status.HTTP_401_UNAUTHORIZED, CredencialesInvalidas),
        (status.HTTP_503_SERVICE_UNAVAILABLE, ErrorDelProveedor),
    ],
)
def test_verificar_token_traduce_el_http_al_dominio(monkeypatch, codigo_http, clase):
    """`verify_cognito_token` nació como dependencia de FastAPI. La interfaz no
    obliga a nadie a conocer el framework, así que la traducción se deshace
    aquí; volverá a hacerse en `deps.py` cuando pase por el proveedor.
    """

    def revienta(_):
        raise HTTPException(status_code=codigo_http, detail="lo que sea")

    monkeypatch.setattr("app.core.security.verify_cognito_token", revienta)

    with pytest.raises(clase):
        CognitoIdentityProvider(_ClienteFalso()).verificar_token("t")

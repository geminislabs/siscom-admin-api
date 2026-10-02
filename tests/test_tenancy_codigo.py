"""
Fase 2, rebanada B: modelos, techo descendente y `GET /tenant-config`.

QUÉ NO SE PRUEBA AQUÍ, Y POR QUÉ
================================
Los triggers que mantienen `account_path` ya los cubren los 38 tests de
`test_tenancy_esquema.py`, que levantan una base desechable con el esquema
productivo más `alembic upgrade head`. Este módulo corre sobre el harness
normal, que construye el esquema con `create_all()` y **por tanto no tiene los
triggers**: aquí el camino se escribe a mano.

Eso es correcto para lo que se está probando —la resolución, que recibe el
camino ya calculado— pero conviene tenerlo escrito para que nadie concluya de
estos tests que escribir `account_path` a mano funciona. En producción no
funciona: el trigger `BEFORE` lo recalcula e ignora lo que traiga el INSERT.
"""

import uuid
from datetime import timedelta

import pytest

from app.models.account import Account, AccountType
from app.models.capability import AccountCapability, Capability
from app.models.tenancy import TenantBranding, TenantDomain
from app.services import account_capabilities as ac
from app.utils.datetime import utcnow

# ─────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────


def _cuenta(db, nombre, padre=None, tipo=AccountType.CUSTOMER):
    """Crea una cuenta y le escribe el camino a mano (no hay triggers aquí)."""
    cid = uuid.uuid4()
    camino = [*padre.account_path, cid] if padre is not None else [cid]
    cuenta = Account(
        id=cid,
        name=nombre,
        parent_account_id=(padre.id if padre is not None else None),
        account_type=tipo,
        account_path=camino,
    )
    db.add(cuenta)
    db.flush()
    return cuenta


def _capability(db, code, value_type):
    cap = Capability(code=code, description=f"cap {code}", value_type=value_type)
    db.add(cap)
    db.flush()
    return cap


def _conceder(db, cuenta, cap, *, entero=None, booleano=None, texto=None, expira=None):
    fila = AccountCapability(
        account_id=cuenta.id,
        capability_id=cap.id,
        value_int=entero,
        value_bool=booleano,
        value_text=texto,
        expires_at=expira,
    )
    db.add(fila)
    db.flush()
    return fila


# ─────────────────────────────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────────────────────────────


def test_ancestros_excluye_la_propia_cuenta(db_session):
    """`account_path` incluye a la cuenta; `ancestros()` no."""
    raiz = _cuenta(db_session, "Mero Mero", tipo=AccountType.RESELLER)
    hija = _cuenta(db_session, "Empresa 1", padre=raiz)

    assert hija.account_path == [raiz.id, hija.id]
    assert hija.ancestros() == [raiz.id]
    assert raiz.ancestros() == []
    assert raiz.es_raiz() and not hija.es_raiz()


def test_cada_marca_es_su_propia_raiz(db_session):
    """
    Dos marcas no comparten raíz, y ése es el punto.

    Si todas colgaran de una cuenta de plataforma, `account_path @> ARRAY[esa]`
    casaría con el sistema entero y existiría un id que significa «todo». Con un
    bosque de raíces, el peor caso de un error de resolución queda contenido en
    una marca.
    """
    una = _cuenta(db_session, "Mero Mero", tipo=AccountType.RESELLER)
    otra = _cuenta(db_session, "Otro Partner", tipo=AccountType.RESELLER)

    assert set(una.account_path).isdisjoint(otra.account_path)


# ─────────────────────────────────────────────────────────────────────
# Techo descendente
# ─────────────────────────────────────────────────────────────────────


def test_el_ancestro_recorta_al_descendiente(db_session):
    """Mero Mero no puede darle a Empresa 500 más de lo que le dieron a él."""
    cap = _capability(db_session, "max_sub_accounts", "int")
    geminis = _cuenta(db_session, "Geminis", tipo=AccountType.PLATFORM)
    mero = _cuenta(db_session, "Mero Mero", padre=geminis, tipo=AccountType.RESELLER)

    _conceder(db_session, geminis, cap, entero=5000)
    _conceder(db_session, mero, cap, entero=9000)  # pide más de lo que tiene

    r = ac.resolver(db_session, mero.id, "max_sub_accounts")
    assert r.value == 5000
    assert r.source == "ancestro"
    assert r.limitado_por == geminis.id


def test_el_descendiente_puede_pedir_menos(db_session):
    cap = _capability(db_session, "max_sub_accounts", "int")
    geminis = _cuenta(db_session, "Geminis", tipo=AccountType.PLATFORM)
    mero = _cuenta(db_session, "Mero Mero", padre=geminis, tipo=AccountType.RESELLER)

    _conceder(db_session, geminis, cap, entero=5000)
    _conceder(db_session, mero, cap, entero=200)

    r = ac.resolver(db_session, mero.id, "max_sub_accounts")
    assert r.value == 200
    assert r.source == "cuenta"
    assert r.limitado_por is None


def test_el_recorte_se_atribuye_a_quien_de_verdad_manda(db_session):
    """
    A(5) -> B(10) -> C(3): el valor final lo pone C, no el recorte de A sobre B.

    Atribuirlo al primer recorte que ocurrió durante el plegado daría una
    explicación falsa a quien pregunte por qué no puede subirlo.
    """
    cap = _capability(db_session, "max_sub_accounts", "int")
    a = _cuenta(db_session, "A", tipo=AccountType.PLATFORM)
    b = _cuenta(db_session, "B", padre=a, tipo=AccountType.RESELLER)
    c = _cuenta(db_session, "C", padre=b)

    _conceder(db_session, a, cap, entero=5)
    _conceder(db_session, b, cap, entero=10)
    _conceder(db_session, c, cap, entero=3)

    r = ac.resolver(db_session, c.id, "max_sub_accounts")
    assert r.value == 3
    assert r.limitado_por is None  # nadie le recortó: pidió menos que el techo
    assert r.source == "cuenta"


def test_sin_fila_hereda_en_vez_de_denegar(db_session):
    """
    Una cuenta sin fila **no** vale cero: hereda el techo de arriba.

    Es la distinción de §17. Si «sin fila» se tratara como cero, el sistema
    denegaría todo hasta configurar cada cuenta una por una.
    """
    cap = _capability(db_session, "max_sub_accounts", "int")
    geminis = _cuenta(db_session, "Geminis", tipo=AccountType.PLATFORM)
    mero = _cuenta(db_session, "Mero Mero", padre=geminis, tipo=AccountType.RESELLER)
    empresa = _cuenta(db_session, "Empresa 1", padre=mero)

    _conceder(db_session, geminis, cap, entero=5000)
    # mero y empresa no tienen fila

    assert ac.resolver(db_session, empresa.id, "max_sub_accounts").value == 5000


def test_sin_nada_en_el_camino_se_usa_el_default(db_session):
    """El default aplica solo cuando nadie dijo nada, nunca como techo más."""
    _capability(db_session, "max_sub_accounts", "int")
    sola = _cuenta(db_session, "Cliente directo")

    r = ac.resolver(db_session, sola.id, "max_sub_accounts")
    assert r.source == "default"
    assert r.value == 0


def test_el_default_no_entra_en_el_plegado(db_session):
    """
    Conceder 5 000 tiene que servir de algo.

    Si el default (0) participara del `min`, el permiso otorgado daría 0 y la
    concesión no serviría para nada.
    """
    cap = _capability(db_session, "max_sub_accounts", "int")
    geminis = _cuenta(db_session, "Geminis", tipo=AccountType.PLATFORM)
    _conceder(db_session, geminis, cap, entero=5000)

    assert ac.resolver(db_session, geminis.id, "max_sub_accounts").value == 5000


def test_un_booleano_falso_arriba_lo_prohibe_abajo(db_session):
    cap = _capability(db_session, "can_resell", "bool")
    geminis = _cuenta(db_session, "Geminis", tipo=AccountType.PLATFORM)
    mero = _cuenta(db_session, "Mero Mero", padre=geminis, tipo=AccountType.RESELLER)

    _conceder(db_session, geminis, cap, booleano=False)
    _conceder(db_session, mero, cap, booleano=True)  # se lo regala a sí mismo

    assert ac.puede(db_session, mero.id, "can_resell") is False


def test_false_no_se_confunde_con_ausencia(db_session):
    """
    `False` es un valor, no un hueco.

    Es §17 en su forma más pequeña: sobre una capability booleana, tomar
    `False` por «no hay fila» convierte un permiso denegado en uno heredado.
    """
    cap = _capability(db_session, "white_label_enabled", "bool")
    geminis = _cuenta(db_session, "Geminis", tipo=AccountType.PLATFORM)
    mero = _cuenta(db_session, "Mero Mero", padre=geminis, tipo=AccountType.RESELLER)

    _conceder(db_session, geminis, cap, booleano=True)
    fila = _conceder(db_session, mero, cap, booleano=False)

    assert fila.get_value() is False
    assert ac.puede(db_session, mero.id, "white_label_enabled") is False


def test_una_fila_caducada_ni_restringe_ni_concede(db_session):
    cap = _capability(db_session, "max_sub_accounts", "int")
    geminis = _cuenta(db_session, "Geminis", tipo=AccountType.PLATFORM)
    mero = _cuenta(db_session, "Mero Mero", padre=geminis, tipo=AccountType.RESELLER)

    _conceder(db_session, geminis, cap, entero=5000)
    _conceder(db_session, mero, cap, entero=10, expira=utcnow() - timedelta(days=1))

    # El recorte caducado desaparece: vuelve a mandar el techo del ancestro.
    assert ac.resolver(db_session, mero.id, "max_sub_accounts").value == 5000


def test_el_texto_no_tiene_techo_gana_el_mas_cercano(db_session):
    """
    Un texto no tiene orden, así que «techo» no significa nada sobre él.

    Se documenta con un test para que el día que se definan los modos de
    `self_signup_mode` la decisión sea consciente y no un descubrimiento.
    """
    cap = _capability(db_session, "self_signup_mode", "text")
    geminis = _cuenta(db_session, "Geminis", tipo=AccountType.PLATFORM)
    mero = _cuenta(db_session, "Mero Mero", padre=geminis, tipo=AccountType.RESELLER)

    _conceder(db_session, geminis, cap, texto="abierto")
    _conceder(db_session, mero, cap, texto="por_invitacion")

    assert (
        ac.resolver(db_session, mero.id, "self_signup_mode").value == "por_invitacion"
    )


def test_un_camino_vacio_es_un_error_no_un_permiso(db_session):
    """
    Sin camino no se decide: se falla.

    Un `account_path` ausente significa que el invariante que sostiene el
    aislamiento no se cumple, y en ese estado la respuesta correcta no es «sin
    límite» ni un silencioso «denegado todo».
    """
    rota = Account(id=uuid.uuid4(), name="Sin camino", account_path=[])
    db_session.add(rota)
    db_session.flush()

    with pytest.raises(ac.CaminoDeCuentaInvalido):
        ac.resolver(db_session, rota.id, "max_sub_accounts")


def test_una_cuenta_inexistente_tambien_falla(db_session):
    with pytest.raises(ac.CaminoDeCuentaInvalido):
        ac.resolver(db_session, uuid.uuid4(), "max_sub_accounts")


def test_validar_limite_trata_el_cero_como_cero(db_session):
    """
    Aquí 0 es cero, no «ilimitado» — al revés que en el servicio de
    organización. Es la razón de que este servicio exista aparte: los defaults
    valen 0 para que una cuenta sin permiso no pueda revender.
    """
    _capability(db_session, "max_sub_accounts", "int")
    sola = _cuenta(db_session, "Cliente directo")

    assert ac.validar_limite(db_session, sola.id, "max_sub_accounts", 0) is False


def test_resolver_todas_ignora_las_capabilities_operativas(db_session):
    """`max_devices` se resuelve por organización; este servicio no opina."""
    _capability(db_session, "max_devices", "int")
    _capability(db_session, "can_resell", "bool")
    cuenta = _cuenta(db_session, "Cliente directo")

    todas = ac.resolver_todas(db_session, cuenta.id)
    assert "can_resell" in todas
    assert "max_devices" not in todas


# ─────────────────────────────────────────────────────────────────────
# GET /tenant-config
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "crudo,esperado",
    [
        ("MeroMero.com", "meromero.com"),
        ("meromero.com:8000", "meromero.com"),
        ("meromero.com.", "meromero.com"),
        ("  meromero.com  ", "meromero.com"),
        ("[::1]:8000", "[::1]"),
        ("", None),
        (None, None),
        ("x" * 300, None),
    ],
)
def test_normalizacion_del_host(crudo, esperado):
    from app.services.tenancy import normalizar_host

    assert normalizar_host(crudo) == esperado


def _marca(db, hostname, *, nombre="Mero Mero", estado="VERIFIED", tema=None):
    cuenta = _cuenta(db, nombre, tipo=AccountType.RESELLER)
    db.add(
        TenantDomain(
            account_id=cuenta.id,
            hostname=hostname,
            is_primary=True,
            status=estado,
            verified_at=(utcnow() if estado == "VERIFIED" else None),
        )
    )
    db.add(
        TenantBranding(
            account_id=cuenta.id,
            brand_name=nombre,
            published=(tema if tema is not None else {}),
        )
    )
    db.commit()
    return cuenta


def test_tenant_config_resuelve_la_marca_por_host(client, db_session):
    _marca(
        db_session,
        "meromero.com",
        tema={"brand-primary": "#0a7", "logo": "https://assets/x.png"},
    )

    r = client.get("/api/v1/tenant-config", headers={"Host": "MeroMero.com"})

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["brand_name"] == "Mero Mero"
    assert cuerpo["hostname"] == "meromero.com"
    assert cuerpo["theme"]["brand-primary"] == "#0a7"
    assert cuerpo["is_default"] is False


def test_tenant_config_no_filtra_identificadores_internos(client, db_session):
    """
    El endpoint es público y enumerable por diseño: solo marca.

    Devolver el `account_id` daría a cualquiera que pruebe hostnames el id que
    después aparece en el predicado de aislamiento.
    """
    cuenta = _marca(db_session, "meromero.com")

    r = client.get("/api/v1/tenant-config", headers={"Host": "meromero.com"})

    crudo = r.text
    assert str(cuenta.id) not in crudo
    assert "account_id" not in crudo


def test_un_dominio_sin_verificar_no_sirve_su_marca(client, db_session):
    """
    Hasta que demuestre control por DNS, cualquiera puede reclamar un hostname.

    Servir su marca antes permitiría suplantar a un partner apuntando un CNAME.
    """
    _marca(db_session, "meromero.com", estado="PENDING")

    r = client.get("/api/v1/tenant-config", headers={"Host": "meromero.com"})

    assert r.status_code == 200
    assert r.json()["is_default"] is True
    assert r.json()["brand_name"] == "Nexus"


def test_un_host_desconocido_responde_200_generico(client):
    """
    Un Host desconocido no es un error.

    Un 404 dejaría la aplicación sin pintar en el caso más probable —un dominio
    recién dado de alta— en vez de pintarla neutra.
    """
    r = client.get("/api/v1/tenant-config", headers={"Host": "no-es-de-nadie.com"})

    assert r.status_code == 200
    assert r.json()["is_default"] is True


def test_tenant_config_no_exige_autenticacion(client, db_session):
    """Hace falta antes de que exista sesión: sin cabecera Authorization."""
    _marca(db_session, "meromero.com")

    r = client.get("/api/v1/tenant-config", headers={"Host": "meromero.com"})

    assert r.status_code == 200


def test_la_respuesta_varia_por_host(client, db_session):
    """
    Sin `Vary: Host`, una caché intermedia serviría la marca de un partner a
    otro — que es exactamente el incidente que este diseño viene a evitar.
    """
    _marca(db_session, "meromero.com")

    r = client.get("/api/v1/tenant-config", headers={"Host": "meromero.com"})

    assert "Host" in r.headers.get("vary", "")
    assert "max-age" in r.headers.get("cache-control", "")


def test_dos_marcas_no_se_ven_entre_si(client, db_session):
    _marca(db_session, "meromero.com", nombre="Mero Mero", tema={"c": "#111"})
    _marca(db_session, "otropartner.com", nombre="Otro Partner", tema={"c": "#222"})

    una = client.get("/api/v1/tenant-config", headers={"Host": "meromero.com"}).json()
    otra = client.get(
        "/api/v1/tenant-config", headers={"Host": "otropartner.com"}
    ).json()

    assert una["brand_name"] == "Mero Mero"
    assert otra["brand_name"] == "Otro Partner"
    assert una["theme"]["c"] != otra["theme"]["c"]

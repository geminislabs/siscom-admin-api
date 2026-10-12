"""Los endpoints de la pantalla de marca (B4, rebanada 2).

Entran por HTTP con la identidad de alguien real, como producción. Cada 403 se
prueba con un token válido —un member, el owner de otra cuenta, el owner de una
cuenta sin `white_label_enabled`—: un test que solo prueba la ausencia de
credencial no prueba la autorización.

El catálogo (`branding.write` para owner y admin) lo siembra el fixture: esta
base sale de `create_all()`. Que la migración `039` siembre lo mismo lo prueba
`tests/test_permisos_esquema.py`.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi import status

from app.models.account import Account
from app.models.account_event import AccountEvent
from app.models.account_user import AccountUser
from app.models.capability import AccountCapability, Capability
from app.models.organization import Organization
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.permission import Permission, Role, RolePermission
from app.models.tenancy import TenantBranding, TenantDomain
from app.models.user import User
from app.utils.datetime import utcnow

_AUTH = {"Authorization": "Bearer lo-que-sea"}

BORRADOR = {
    "brand_name": "Mero Mero",
    "logo_url": "https://cdn.meromero.com/logo.png",
    "support_email": "soporte@meromero.com",
    "legal_url": "https://meromero.com/legal",
    "seed": {"primary": "#2563EB"},
}


def _como(usuario):
    return patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": usuario.cognito_sub}
    )


@pytest.fixture
def catalogo(db_session):
    roles = {}
    for code in ("owner", "admin", "billing", "member"):
        rol = Role(scope="account", code=code, name=code, is_system=True)
        db_session.add(rol)
        roles[code] = rol
    db_session.add(
        Permission(code="branding.write", description="Marca", scope="account")
    )
    db_session.flush()
    for code in ("owner", "admin"):
        db_session.add(
            RolePermission(
                role_id=roles[code].id,
                permission_code="branding.write",
                scope="account",
            )
        )
    db_session.commit()


@pytest.fixture
def marca_blanca(db_session):
    cap = Capability(
        code="white_label_enabled", description="Marca propia", value_type="bool"
    )
    db_session.add(cap)
    db_session.commit()
    return cap


def _cuenta(db_session, nombre, *, padre=None, marca=None, valor=True):
    cid = uuid.uuid4()
    camino = [*padre.account_path, cid] if padre is not None else [cid]
    cuenta = Account(
        id=cid,
        name=nombre,
        status="ACTIVE",
        parent_account_id=padre.id if padre is not None else None,
        account_path=camino,
    )
    db_session.add(cuenta)
    db_session.flush()
    if marca is not None:
        db_session.add(
            AccountCapability(account_id=cid, capability_id=marca.id, value_bool=valor)
        )
    org = Organization(id=uuid.uuid4(), account_id=cid, name=nombre, status="ACTIVE")
    db_session.add(org)
    db_session.commit()
    return cuenta, org


def _persona(db_session, cuenta, org, rol, correo):
    user = User(
        id=uuid.uuid4(),
        default_organization_id=org.id,
        cognito_sub=f"sub-{correo}",
        external_id=correo,
        email=correo,
        full_name="Quien Sea",
        is_master=False,
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        OrganizationUser(
            organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER.value
        )
    )
    db_session.add(AccountUser(account_id=cuenta.id, user_id=user.id, role=rol))
    db_session.commit()
    return user


@pytest.fixture
def partner(db_session, catalogo, marca_blanca):
    """Una cuenta con marca propia, su owner y un dominio verificado."""
    cuenta, org = _cuenta(db_session, "Mero Mero", marca=marca_blanca)
    owner = _persona(db_session, cuenta, org, "owner", "owner@meromero.com")
    db_session.add(
        TenantDomain(
            account_id=cuenta.id,
            hostname="meromero.com",
            is_primary=True,
            status="VERIFIED",
            verified_at=utcnow(),
        )
    )
    db_session.commit()
    return cuenta, org, owner


def _url(cuenta, resto=""):
    return f"/api/v1/accounts/{cuenta.id}/branding{resto}"


def _eventos(db_session, cuenta):
    db_session.expire_all()
    return [
        e.event_type
        for e in db_session.query(AccountEvent)
        .filter(AccountEvent.account_id == cuenta.id)
        .order_by(AccountEvent.created_at)
        .all()
    ]


# ── Lectura ─────────────────────────────────────────────────────────────


def test_sin_fila_todavia_el_get_responde_vacio(client, partner):
    cuenta, _, owner = partner
    with _como(owner):
        r = client.get(_url(cuenta), headers=_AUTH)

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {
        "account_id": str(cuenta.id),
        "brand_name": None,
        "draft": None,
        "published": {},
        "published_at": None,
        "published_by": None,
    }


# ── Guardar el borrador ─────────────────────────────────────────────────


def test_guardar_deriva_los_tokens_y_no_toca_lo_publicado(client, db_session, partner):
    cuenta, _, owner = partner
    with _como(owner):
        r = client.put(_url(cuenta, "/draft"), json=BORRADOR, headers=_AUTH)

    assert r.status_code == status.HTTP_200_OK
    cuerpo = r.json()
    borrador = cuerpo["draft"]
    assert borrador["version"] == 1
    assert borrador["brand_name"] == "Mero Mero"
    assert borrador["seed"] == {"primary": "#2563eb"}
    assert borrador["tokens"]["light"]["--color-brand-primary"] == "#2563eb"
    assert set(borrador["tokens"]) == {"light", "dark"}
    assert cuerpo["contrast"] and all(
        p["ratio"] >= p["minimo"] for p in cuerpo["contrast"]
    )
    # Lo publicado sigue como estaba, nombre incluido.
    assert cuerpo["brand_name"] is None
    assert cuerpo["published"] == {}
    assert _eventos(db_session, cuenta) == ["branding_draft_saved"]


def test_los_tokens_de_la_peticion_se_ignoran(client, partner):
    """El partner nunca escribe tokens: los deriva el servidor."""
    cuenta, _, owner = partner
    trampa = {
        **BORRADOR,
        "version": 99,
        "tokens": {"light": {"--color-brand-primary": "#ffff00"}},
    }
    with _como(owner):
        r = client.put(_url(cuenta, "/draft"), json=trampa, headers=_AUTH)

    assert r.status_code == status.HTTP_200_OK
    borrador = r.json()["draft"]
    assert borrador["version"] == 1
    assert borrador["tokens"]["light"]["--color-brand-primary"] == "#2563eb"


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("logo_url", "http://cdn.meromero.com/logo.png"),
        ("logo_url", "https://usuario:clave@cdn.meromero.com/logo.png"),
        ("logo_url", "https://169.254.169.254/latest/meta-data/"),
        ("logo_url", "https://10.8.0.1/logo.png"),
        ("logo_url", "https://localhost/logo.png"),
        ("logo_url", "https://" + "a" * 2050 + ".com/x.png"),
        ("legal_url", "javascript:alert(1)"),
        ("support_email", "no-es-correo"),
        ("brand_name", "   "),
        ("seed", {"primary": "azul"}),
        ("seed", {"primary": "#2563eb", "otro": "#000000"}),
        ("logo_ulr", "https://cdn.meromero.com/logo.png"),
    ],
)
def test_lo_que_no_es_valido_es_422(client, db_session, partner, campo, valor):
    cuenta, _, owner = partner
    with _como(owner):
        r = client.put(
            _url(cuenta, "/draft"), json={**BORRADOR, campo: valor}, headers=_AUTH
        )

    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert _eventos(db_session, cuenta) == []


def test_un_par_que_no_pasa_aa_es_422_con_el_par_y_su_ratio(client, partner):
    """La derivación nunca produce un par que falle (lo barre
    `test_marca_tema.py`), así que el camino se prueba subiendo el mínimo."""
    cuenta, _, owner = partner
    with _como(owner), patch("app.services.marca_tema.AA_TEXTO", 30.0):
        r = client.put(_url(cuenta, "/draft"), json=BORRADOR, headers=_AUTH)

    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    detalle = r.json()["detail"]
    assert detalle["code"] == "contraste_insuficiente"
    par = detalle["pairs"][0]
    assert {"modo", "par", "colores", "ratio", "minimo"} <= set(par)
    assert par["ratio"] < par["minimo"] == 30.0


# ── /tenant-config no sirve el borrador ────────────────────────────────


def test_tenant_config_nunca_sirve_el_borrador(client, partner):
    cuenta, _, owner = partner
    with _como(owner):
        client.put(_url(cuenta, "/draft"), json=BORRADOR, headers=_AUTH)

    r = client.get("/api/v1/tenant-config", headers={"Host": "meromero.com"})

    assert r.status_code == status.HTTP_200_OK
    assert r.json()["brand_name"] == "Nexus"
    assert r.json()["theme"] == {}


# ── Publicar ────────────────────────────────────────────────────────────


def test_publicar_sin_borrador_es_409(client, partner):
    cuenta, _, owner = partner
    with _como(owner):
        r = client.post(_url(cuenta, "/publish"), headers=_AUTH)

    assert r.status_code == status.HTTP_409_CONFLICT


def test_publicar_cambia_lo_que_ven_los_usuarios(client, db_session, partner):
    cuenta, _, owner = partner
    with _como(owner):
        client.put(_url(cuenta, "/draft"), json=BORRADOR, headers=_AUTH)
        r = client.post(_url(cuenta, "/publish"), headers=_AUTH)

    assert r.status_code == status.HTTP_200_OK
    cuerpo = r.json()
    assert cuerpo["draft"] is None
    assert cuerpo["brand_name"] == "Mero Mero"
    assert cuerpo["published_by"] == str(owner.id)
    assert cuerpo["published_at"] is not None
    # El nombre vive en la columna, no dentro del jsonb publicado.
    assert "brand_name" not in cuerpo["published"]
    assert cuerpo["published"]["logo_url"] == BORRADOR["logo_url"]
    assert cuerpo["published"]["support_email"] == BORRADOR["support_email"]

    config = client.get("/api/v1/tenant-config", headers={"Host": "meromero.com"})
    assert config.json()["brand_name"] == "Mero Mero"
    assert config.json()["theme"]["logo_url"] == BORRADOR["logo_url"]
    assert (
        config.json()["theme"]["tokens"]["light"]["--color-brand-primary"] == "#2563eb"
    )


def test_publicar_deja_lo_anterior_en_la_auditoria(client, db_session, partner):
    """Volver atrás es publicar lo que había: tiene que estar guardado."""
    cuenta, _, owner = partner
    with _como(owner):
        client.put(_url(cuenta, "/draft"), json=BORRADOR, headers=_AUTH)
        client.post(_url(cuenta, "/publish"), headers=_AUTH)
        client.put(
            _url(cuenta, "/draft"),
            json={**BORRADOR, "brand_name": "Mero Mero 2"},
            headers=_AUTH,
        )
        client.post(_url(cuenta, "/publish"), headers=_AUTH)

    # Las dos publicaciones comparten `created_at`: el harness corre todo en
    # una transacción y `now()` es la hora de su inicio. Por eso no se ordena.
    db_session.expire_all()
    publicaciones = (
        db_session.query(AccountEvent)
        .filter(
            AccountEvent.account_id == cuenta.id,
            AccountEvent.event_type == "branding_published",
        )
        .all()
    )
    anteriores = {e.event_metadata["anterior"]["brand_name"]: e for e in publicaciones}
    assert set(anteriores) == {None, "Mero Mero"}
    segunda = anteriores["Mero Mero"]
    assert segunda.event_metadata["anterior"]["published"]["logo_url"] == (
        BORRADOR["logo_url"]
    )
    assert anteriores[None].event_metadata["anterior"]["published"] == {}
    assert segunda.actor_user_id == owner.id


# ── Descartar ───────────────────────────────────────────────────────────


def test_descartar_borra_el_borrador_y_deja_lo_publicado(client, db_session, partner):
    cuenta, _, owner = partner
    with _como(owner):
        client.put(_url(cuenta, "/draft"), json=BORRADOR, headers=_AUTH)
        client.post(_url(cuenta, "/publish"), headers=_AUTH)
        client.put(
            _url(cuenta, "/draft"),
            json={**BORRADOR, "brand_name": "Otro"},
            headers=_AUTH,
        )
        r = client.delete(_url(cuenta, "/draft"), headers=_AUTH)
        despues = client.get(_url(cuenta), headers=_AUTH).json()

    assert r.status_code == status.HTTP_204_NO_CONTENT
    assert despues["draft"] is None
    assert despues["brand_name"] == "Mero Mero"
    assert _eventos(db_session, cuenta)[-1] == "branding_draft_discarded"


def test_descartar_sin_borrador_es_204_y_no_audita(client, db_session, partner):
    cuenta, _, owner = partner
    with _como(owner):
        r = client.delete(_url(cuenta, "/draft"), headers=_AUTH)

    assert r.status_code == status.HTTP_204_NO_CONTENT
    assert _eventos(db_session, cuenta) == []


# ── Quién puede ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("rol", ["owner", "admin"])
def test_owner_y_admin_de_la_cuenta_pueden(client, db_session, partner, rol):
    cuenta, org, _ = partner
    persona = _persona(db_session, cuenta, org, rol, f"{rol}2@meromero.com")
    with _como(persona):
        r = client.put(_url(cuenta, "/draft"), json=BORRADOR, headers=_AUTH)
    assert r.status_code == status.HTTP_200_OK


@pytest.mark.parametrize("rol", ["billing", "member"])
@pytest.mark.parametrize(
    "metodo, resto",
    [("get", ""), ("put", "/draft"), ("post", "/publish"), ("delete", "/draft")],
)
def test_billing_y_member_reciben_403_en_los_cuatro(
    client, db_session, partner, rol, metodo, resto
):
    cuenta, org, _ = partner
    persona = _persona(db_session, cuenta, org, rol, f"{rol}@meromero.com")
    kwargs = {"json": BORRADOR} if metodo == "put" else {}
    with _como(persona):
        r = getattr(client, metodo)(_url(cuenta, resto), headers=_AUTH, **kwargs)
    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_el_owner_de_otra_cuenta_recibe_403(client, db_session, partner, marca_blanca):
    cuenta, _, _ = partner
    otra, org_otra = _cuenta(db_session, "Otra", marca=marca_blanca)
    ajeno = _persona(db_session, otra, org_otra, "owner", "owner@otra.com")
    with _como(ajeno):
        r = client.put(_url(cuenta, "/draft"), json=BORRADOR, headers=_AUTH)
    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_sin_white_label_el_owner_recibe_403(client, db_session, catalogo):
    cuenta, org = _cuenta(db_session, "Sin marca")
    owner = _persona(db_session, cuenta, org, "owner", "owner@sinmarca.com")
    with _como(owner):
        r = client.get(_url(cuenta), headers=_AUTH)
    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_si_el_ancestro_no_tiene_white_label_la_hija_tampoco(
    client, db_session, catalogo, marca_blanca
):
    """El techo descendente (D3): la hija pide True, el padre dice False."""
    padre, _ = _cuenta(db_session, "Padre", marca=marca_blanca, valor=False)
    hija, org = _cuenta(db_session, "Hija", padre=padre, marca=marca_blanca)
    owner = _persona(db_session, hija, org, "owner", "owner@hija.com")
    with _como(owner):
        r = client.get(_url(hija), headers=_AUTH)
    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_un_camino_de_cuenta_roto_es_403(client, db_session, partner):
    cuenta, _, owner = partner
    fila = db_session.get(Account, cuenta.id)
    fila.account_path = []
    db_session.commit()
    with _como(owner):
        r = client.get(_url(cuenta), headers=_AUTH)
    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_sin_credencial_es_401(client, partner):
    cuenta, _, _ = partner
    r = client.get(_url(cuenta))
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


def test_el_borrador_de_otra_cuenta_no_se_ve(client, db_session, partner):
    """Escribir en una cuenta no deja rastro en otra."""
    cuenta, _, owner = partner
    with _como(owner):
        client.put(_url(cuenta, "/draft"), json=BORRADOR, headers=_AUTH)
    otras = (
        db_session.query(TenantBranding)
        .filter(TenantBranding.account_id != cuenta.id)
        .count()
    )
    assert otras == 0

"""`GET /users` expone `status` — el paso 3 de la baja en Nexus.

`UserOut` no devolvía `status` desde que la 029 lo creó en la fila
(`v1.32.2`). `AdminDashboard.svelte:21` en nexus-web-page ya comprobaba
`u.status !== 'pending'` contra un campo que nunca llegaba — y 'pending'
tampoco es un valor posible (`ck_users_status` sólo tiene ACTIVE/INACTIVE), así
que esa condición nunca excluyó a nadie. Este test prueba sólo el lado del
API: que el campo llega con el valor real de la fila.
"""

from fastapi import status as http_status


def test_get_users_expone_el_estado_de_la_fila(authenticated_client, test_user_data):
    respuesta = authenticated_client.get("/api/v1/users")

    assert respuesta.status_code == http_status.HTTP_200_OK
    cuerpo = respuesta.json()
    fila = next(u for u in cuerpo if u["id"] == str(test_user_data.id))
    assert fila["status"] == "ACTIVE"


def test_get_users_expone_inactive_para_una_fila_desactivada(
    authenticated_client, db_session, test_organization_data, test_user_data
):
    from uuid import uuid4

    from app.models.organization_user import OrganizationRole, OrganizationUser
    from app.models.user import User, UserStatus

    inactivo = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        cognito_sub="sub-inactivo",
        external_id="inactivo@example.com",
        email="inactivo@example.com",
        full_name="Ex Miembro",
        is_master=False,
        status=UserStatus.INACTIVE.value,
    )
    db_session.add(inactivo)
    db_session.flush()
    db_session.add(
        OrganizationUser(
            organization_id=test_organization_data.id,
            user_id=inactivo.id,
            role=OrganizationRole.MEMBER.value,
        )
    )
    db_session.commit()

    respuesta = authenticated_client.get("/api/v1/users")

    assert respuesta.status_code == http_status.HTTP_200_OK
    fila = next(u for u in respuesta.json() if u["id"] == str(inactivo.id))
    assert fila["status"] == "INACTIVE"

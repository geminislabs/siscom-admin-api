#!/usr/bin/env python3
"""
Crea (o reutiliza) el usuario técnico Siscom para registered_by en pagos manuales GAC.

Uso:
  cd siscom-admin-api
  .venv/bin/python scripts/seed_gac_system_user.py --organization-id <UUID>

Imprime el UUID para GAC_SYSTEM_USER_ID en .env

La organización se pide explícita: `users.default_organization_id` es NOT NULL y
el listado interno de usuarios filtra por esa columna, así que el usuario
aparece en esa organización. Debe ser la organización interna de Geminis, nunca
la de un cliente.

El usuario nace INACTIVE y sin membresía: solo existe para que
`payments.registered_by` tenga a quién apuntar. Su `cognito_sub` no es un sub
real de Cognito, así que tampoco puede iniciar sesión.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal
from app.models.organization import Organization
from app.models.user import User, UserStatus

GAC_SYSTEM_EMAIL = "gac-system-registered-by@internal.geminislabs.io"
GAC_SYSTEM_COGNITO_SUB = "gac-system-registered-by"
GAC_SYSTEM_FULL_NAME = "GAC Sistema (pagos manuales)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crea el usuario técnico para GAC_SYSTEM_USER_ID"
    )
    parser.add_argument(
        "--organization-id",
        required=True,
        type=UUID,
        help="Organización interna de Geminis (no la de un cliente)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = (
            db.query(User)
            .filter(User.email == GAC_SYSTEM_EMAIL, User.brand_account_id.is_(None))
            .first()
        )
        if existing:
            print(f"Usuario ya existe: {existing.email}")
            print(f"GAC_SYSTEM_USER_ID={existing.id}")
            return 0

        org = db.get(Organization, args.organization_id)
        if not org:
            print(f"No existe la organización {args.organization_id}", file=sys.stderr)
            return 1

        user = User(
            id=uuid4(),
            default_organization_id=org.id,
            cognito_sub=GAC_SYSTEM_COGNITO_SUB,
            email=GAC_SYSTEM_EMAIL,
            full_name=GAC_SYSTEM_FULL_NAME,
            email_verified=True,
            is_master=False,
            password_hash="",
            status=UserStatus.INACTIVE.value,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"Usuario creado: {user.email}")
        print(f"organization_id={org.id} ({org.name})")
        print(f"GAC_SYSTEM_USER_ID={user.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

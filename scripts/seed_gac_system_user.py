#!/usr/bin/env python3
"""
Crea (o reutiliza) el usuario técnico Siscom para registered_by en pagos manuales GAC.

Uso:
  cd siscom-admin-api
  .venv/bin/python scripts/seed_gac_system_user.py

Imprime el UUID para GAC_SYSTEM_USER_ID en .env
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.organization import Organization
from app.models.user import User

GAC_SYSTEM_EMAIL = "gac-system-registered-by@internal.geminislabs.io"
GAC_SYSTEM_COGNITO_SUB = "gac-system-registered-by"
GAC_SYSTEM_FULL_NAME = "GAC Sistema (pagos manuales)"


def resolve_organization_id(db: Session) -> str:
    org = db.query(Organization).order_by(Organization.created_at.asc()).first()
    if not org:
        raise RuntimeError(
            "No hay organizaciones en la BD. Crea al menos una cuenta/org antes de este script."
        )
    return str(org.id)


def main() -> int:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == GAC_SYSTEM_EMAIL).first()
        if existing:
            print(f"Usuario ya existe: {existing.email}")
            print(f"GAC_SYSTEM_USER_ID={existing.id}")
            return 0

        org_id = resolve_organization_id(db)
        user = User(
            id=uuid4(),
            organization_id=org_id,
            cognito_sub=GAC_SYSTEM_COGNITO_SUB,
            email=GAC_SYSTEM_EMAIL,
            full_name=GAC_SYSTEM_FULL_NAME,
            email_verified=True,
            is_master=False,
            password_hash="",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"Usuario creado: {user.email}")
        print(f"organization_id={org_id}")
        print(f"GAC_SYSTEM_USER_ID={user.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Script para crear SIMs de prueba en la base de datos.

Crea SIMs sin asignar a dispositivos para poder probar
la funcionalidad de asignación desde el frontend.

Uso:
    cd siscom-admin-api--feature-sim-assigning
    source .venv/bin/activate
    python scripts/seed_test_sims.py
"""

import os
import sys
import uuid
from datetime import datetime

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.sim_card import SimCard
from app.models.sim_kore_profile import SimKoreProfile

# Datos de SIMs de prueba
TEST_SIMS = [
    {
        "iccid": "89340100000000000001",
        "imsi": "234100000000001",
        "msisdn": "+525500000001",
        "kore_sim_id": "HStest0001abc123def456789000000001",
        "kore_account_id": "ACtest001",
    },
    {
        "iccid": "89340100000000000002",
        "imsi": "234100000000002",
        "msisdn": "+525500000002",
        "kore_sim_id": "HStest0002abc123def456789000000002",
        "kore_account_id": "ACtest001",
    },
    {
        "iccid": "89340100000000000003",
        "imsi": "234100000000003",
        "msisdn": "+525500000003",
        "kore_sim_id": "HStest0003abc123def456789000000003",
        "kore_account_id": "ACtest001",
    },
    {
        "iccid": "89340100000000000004",
        "imsi": "234100000000004",
        "msisdn": "+525500000004",
        "kore_sim_id": "HStest0004abc123def456789000000004",
        "kore_account_id": "ACtest002",
    },
    {
        "iccid": "89340100000000000005",
        "imsi": "234100000000005",
        "msisdn": "+525500000005",
        "kore_sim_id": "HStest0005abc123def456789000000005",
        "kore_account_id": "ACtest002",
    },
]


def seed_test_sims():
    """Crea SIMs de prueba si no existen."""
    db = SessionLocal()

    try:
        created_count = 0
        skipped_count = 0

        for sim_data in TEST_SIMS:
            # Verificar si ya existe por ICCID
            existing = (
                db.query(SimCard).filter(SimCard.iccid == sim_data["iccid"]).first()
            )

            if existing:
                print(f"  [SKIP] SIM {sim_data['iccid']} ya existe")
                skipped_count += 1
                continue

            # Crear SimCard (sin device_id = disponible para asignación)
            sim_card = SimCard(
                sim_id=uuid.uuid4(),
                device_id=None,  # Sin asignar
                carrier="KORE",
                iccid=sim_data["iccid"],
                imsi=sim_data["imsi"],
                msisdn=sim_data["msisdn"],
                status="active",
                metadata_={
                    "kore": {
                        "sid": sim_data["kore_sim_id"],
                        "account_sid": sim_data["kore_account_id"],
                        "source": "test_seed",
                    }
                },
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(sim_card)
            db.flush()  # Para obtener el sim_id

            # Crear SimKoreProfile
            kore_profile = SimKoreProfile(
                sim_id=sim_card.sim_id,
                kore_sim_id=sim_data["kore_sim_id"],
                kore_account_id=sim_data["kore_account_id"],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(kore_profile)

            print(
                f"  [OK] SIM {sim_data['iccid']} creada (KORE ID: {sim_data['kore_sim_id'][:20]}...)"
            )
            created_count += 1

        db.commit()

        print("\n" + "=" * 50)
        print(f"Resultado: {created_count} SIMs creadas, {skipped_count} omitidas")
        print("=" * 50)

        # Mostrar SIMs disponibles
        available = db.query(SimCard).filter(SimCard.device_id.is_(None)).count()
        print(f"\nSIMs disponibles para asignación: {available}")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Seed de SIMs de prueba para KORE")
    print("=" * 50 + "\n")
    seed_test_sims()

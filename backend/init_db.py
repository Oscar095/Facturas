"""Inicializa la base de datos: crea el esquema, las tablas y el usuario admin.

Uso:
    python init_db.py
Variables opcionales: ADMIN_EMAIL, ADMIN_PASSWORD
"""
import logging
import os

from app.database import Base, SessionLocal, crear_esquema_si_falta, engine
from app.models import Usuario
from app.security import hash_clave

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("init_db")


def main():
    log.info("Creando esquema (si falta)…")
    crear_esquema_si_falta()
    log.info("Creando tablas…")
    Base.metadata.create_all(engine)

    db = SessionLocal()
    try:
        if db.query(Usuario).count() == 0:
            email = os.getenv("ADMIN_EMAIL", "admin@kos.com").lower()
            clave = os.getenv("ADMIN_PASSWORD", "admin1234")
            db.add(Usuario(email=email, nombre="Administrador", rol="admin",
                           hash_clave=hash_clave(clave)))
            db.commit()
            log.info("Usuario admin creado: %s", email)
        else:
            log.info("Ya existen usuarios; no se crea admin.")
    finally:
        db.close()
    log.info("Listo.")


if __name__ == "__main__":
    main()

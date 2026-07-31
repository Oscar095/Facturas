import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, crear_esquema_si_falta, engine
from .models import Rol, Usuario
from .routers import (
    areas, auth, documentos, facturas, firmas, jobs, notas_credito, panel, roles, usuarios,
)
from .security import PERMISOS_LEGADO, hash_clave

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Portal de Recepción de Facturas", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, facturas, documentos, areas, usuarios, jobs, panel, firmas, roles, notas_credito):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True}


_DESCRIPCION_ROLES = {
    "admin": "Acceso total: administración, facturas y contabilización",
    "contabilidad": "Ve todas las áreas, edita facturas, aprueba y contabiliza",
    "area": "Solo su área: carga documentos, procesa y aprueba",
}


def _sembrar_roles(db):
    """Crea los roles de sistema si faltan (idempotente, corre en cada arranque)."""
    existentes = {r.nombre for r in db.query(Rol).all()}
    for nombre, permisos in PERMISOS_LEGADO.items():
        if nombre not in existentes:
            db.add(Rol(nombre=nombre, descripcion=_DESCRIPCION_ROLES[nombre],
                       es_sistema=True, **permisos))
    db.commit()


def _crear_tablas_y_admin():
    crear_esquema_si_falta()
    Base.metadata.create_all(engine)
    # Semilla del admin inicial (solo si no hay usuarios)
    db = SessionLocal()
    try:
        _sembrar_roles(db)
        if db.query(Usuario).count() == 0:
            email = os.getenv("ADMIN_EMAIL", "admin@local")
            clave = os.getenv("ADMIN_PASSWORD", "admin1234")
            db.add(Usuario(email=email.lower(), nombre="Administrador",
                           rol="admin", hash_clave=hash_clave(clave)))
            db.commit()
            logging.info("Usuario admin inicial creado: %s", email)
    finally:
        db.close()


@app.on_event("startup")
def startup():
    _crear_tablas_y_admin()


# ── Servir el frontend React compilado (si existe) ────────────────────────────
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{ruta_completa:path}")
    def spa(ruta_completa: str):
        # Cualquier ruta no-API sirve el index.html (enrutamiento del lado cliente).
        # index.html referencia archivos con hash (ej. index-abc123.js) que cambian
        # en cada build; si el navegador cachea el index.html viejo, pide un archivo
        # que ya no existe y la app queda en blanco. Por eso nunca se cachea.
        archivo = _DIST / ruta_completa
        if archivo.is_file():
            return FileResponse(archivo)
        return FileResponse(_DIST / "index.html", headers={"Cache-Control": "no-cache"})

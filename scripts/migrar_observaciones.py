"""Migración: facturas.observaciones (nota para el jefe aprobador).

Texto libre que escribe quien carga los documentos de la factura, para dar
contexto a quien aprueba (por qué falta un documento, a qué proyecto va, etc.).

Es idempotente. IMPORTANTE: correr contra la BD ANTES de reiniciar el backend
con el models.py nuevo — create_all() no altera tablas existentes, así que si el
modelo trae la columna y la BD no, CUALQUIER select sobre Factura revienta con
"Invalid column name" y se cae todo el listado.

Uso: .venv/Scripts/python.exe scripts/migrar_observaciones.py
"""
import sys

sys.path.insert(0, "backend")

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402


def _existe(con, tabla: str, columna: str) -> bool:
    if settings.usa_sqlite:
        cols = [r[1] for r in con.execute(text(f"PRAGMA table_info({tabla})"))]
        return columna in cols
    return con.execute(
        text(f"SELECT COL_LENGTH('{settings.db_schema}.{tabla}', '{columna}')")
    ).scalar() is not None


if __name__ == "__main__":
    with engine.begin() as con:
        if _existe(con, "facturas", "observaciones"):
            print("La columna facturas.observaciones ya existía.")
        elif settings.usa_sqlite:
            con.execute(text("ALTER TABLE facturas ADD COLUMN observaciones TEXT"))
            print("Columna facturas.observaciones creada (SQLite).")
        else:
            con.execute(text(
                f"ALTER TABLE [{settings.db_schema}].[facturas] ADD observaciones NVARCHAR(MAX) NULL"
            ))
            print("Columna facturas.observaciones creada (SQL Server).")
    print("Migración de observaciones completada.")

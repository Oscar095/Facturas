"""Migración: moneda extranjera y vencimiento en facturas.

Agrega a la tabla facturas:
  - fecha_vencimiento DATETIME NULL (el JSON del portal aún no la trae; la
    llena por ahora solo la carga manual)
  - moneda VARCHAR(10) NOT NULL DEFAULT 'COP'  (COP | USD)
  - trm NUMERIC(18,4) NULL             (tasa de cambio usada al convertir)
  - valor_original NUMERIC(18,2) NULL  (valor en la moneda original; el
    valor_total y el iva quedan SIEMPRE convertidos a COP)

Es idempotente. IMPORTANTE: correr contra la BD ANTES de reiniciar el backend
con el models.py nuevo (create_all() no altera tablas existentes).

Uso: .venv/Scripts/python.exe scripts/migrar_moneda_vencimiento.py
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


def _agregar(con, tabla: str, columna: str, tipo_sqlite: str, tipo_mssql: str,
             default_sql: str | None = None):
    if _existe(con, tabla, columna):
        print(f"La columna {tabla}.{columna} ya existía.")
        return
    if settings.usa_sqlite:
        extra = f" NOT NULL DEFAULT {default_sql}" if default_sql else ""
        con.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo_sqlite}{extra}"))
    else:
        esquema = settings.db_schema
        if default_sql:
            con.execute(text(
                f"ALTER TABLE [{esquema}].[{tabla}] ADD {columna} {tipo_mssql} NOT NULL "
                f"CONSTRAINT DF_{tabla}_{columna} DEFAULT {default_sql}"
            ))
        else:
            con.execute(text(f"ALTER TABLE [{esquema}].[{tabla}] ADD {columna} {tipo_mssql} NULL"))
    print(f"Columna {tabla}.{columna} creada.")


if __name__ == "__main__":
    with engine.begin() as con:
        _agregar(con, "facturas", "fecha_vencimiento", "DATETIME", "DATETIME")
        _agregar(con, "facturas", "moneda", "TEXT", "VARCHAR(10)", "'COP'")
        _agregar(con, "facturas", "trm", "NUMERIC", "NUMERIC(18,4)")
        _agregar(con, "facturas", "valor_original", "NUMERIC", "NUMERIC(18,2)")
    print("Migración de moneda/vencimiento completada.")

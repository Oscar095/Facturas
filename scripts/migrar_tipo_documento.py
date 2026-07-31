"""Migración: agrega facturas.tipo_documento y ejecuciones.notas_credito_nuevas
(columnas NOT NULL con DEFAULT, para no romper las filas existentes), y crea la
tabla notas_credito si falta.

Es idempotente. IMPORTANTE: correr esto contra la base de datos ANTES de
reiniciar el backend con el models.py nuevo — create_all() no altera tablas
existentes, así que si el backend arranca con `tipo_documento` en el modelo
pero la columna no existe aún, cualquier SELECT sobre Factura falla con
"Invalid column name" (rompe todo el listado de facturas, no solo lo nuevo).

Uso: .venv/Scripts/python.exe scripts/migrar_tipo_documento.py
"""
import sys

sys.path.insert(0, "backend")

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.models import NotaCredito  # noqa: E402 (registra la tabla en Base.metadata)


def _agregar_columna(con, tabla: str, columna: str, tipo_sqlite: str, tipo_mssql: str, default_sql: str):
    if settings.usa_sqlite:
        cols = [r[1] for r in con.execute(text(f"PRAGMA table_info({tabla})"))]
        if columna not in cols:
            con.execute(text(
                f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo_sqlite} NOT NULL DEFAULT {default_sql}"
            ))
            print(f"Columna {tabla}.{columna} creada (SQLite).")
        else:
            print(f"La columna {tabla}.{columna} ya existía (SQLite).")
        return

    esquema = settings.db_schema
    existe = con.execute(
        text(f"SELECT COL_LENGTH('{esquema}.{tabla}', '{columna}')")
    ).scalar()
    if existe is None:
        con.execute(text(
            f"ALTER TABLE [{esquema}].[{tabla}] ADD {columna} {tipo_mssql} NOT NULL "
            f"CONSTRAINT DF_{tabla}_{columna} DEFAULT {default_sql}"
        ))
        print(f"Columna {tabla}.{columna} creada (SQL Server).")
    else:
        print(f"La columna {tabla}.{columna} ya existía (SQL Server).")


def agregar_columnas():
    with engine.begin() as con:
        _agregar_columna(con, "facturas", "tipo_documento", "TEXT", "VARCHAR(20)", "'FACTURA'")
        _agregar_columna(con, "ejecuciones", "notas_credito_nuevas", "INTEGER", "INT", "0")


def crear_tabla_notas_credito():
    Base.metadata.create_all(engine, tables=[NotaCredito.__table__])
    print("Tabla notas_credito verificada/creada.")


if __name__ == "__main__":
    agregar_columnas()
    crear_tabla_notas_credito()

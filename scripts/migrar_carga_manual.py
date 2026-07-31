"""Migración para el módulo "Cargar factura" (facturas físicas/de correo):

1. Agrega facturas.origen ('portal' | 'manual', NOT NULL DEFAULT 'portal').
2. En SQL Server, reemplaza el índice/constraint único de facturas.cufe por un
   ÍNDICE ÚNICO FILTRADO (WHERE cufe IS NOT NULL): las facturas manuales pueden
   venir sin CUFE y SQL Server trata varios NULL como duplicados en un UNIQUE
   normal (mismo patrón que reglas_area). En SQLite no hace falta (NULL≠NULL).

Es idempotente. IMPORTANTE: correr contra la BD ANTES de reiniciar el backend
con el models.py nuevo (create_all() no altera tablas existentes).

Uso: .venv/Scripts/python.exe scripts/migrar_carga_manual.py
"""
import sys

sys.path.insert(0, "backend")

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402


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


def _filtrar_indice_cufe(con):
    """SQL Server: vuelve filtrado el índice único de facturas.cufe."""
    if settings.usa_sqlite:
        print("SQLite permite varios NULL en índices únicos — sin cambios al índice.")
        return

    esquema = settings.db_schema
    filas = con.execute(text(f"""
        SELECT i.name, i.has_filter, i.is_unique_constraint
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE i.object_id = OBJECT_ID('{esquema}.facturas')
          AND c.name = 'cufe' AND i.is_unique = 1
    """)).fetchall()

    if any(f.has_filter for f in filas):
        print("El índice único filtrado de facturas.cufe ya existía.")
        return

    for f in filas:
        if f.is_unique_constraint:
            con.execute(text(f"ALTER TABLE [{esquema}].[facturas] DROP CONSTRAINT [{f.name}]"))
        else:
            con.execute(text(f"DROP INDEX [{f.name}] ON [{esquema}].[facturas]"))
        print(f"Índice/constraint único previo de cufe eliminado: {f.name}")

    con.execute(text(
        f"CREATE UNIQUE NONCLUSTERED INDEX ix_facturas_cufe "
        f"ON [{esquema}].[facturas](cufe) WHERE cufe IS NOT NULL"
    ))
    print("Índice único filtrado ix_facturas_cufe creado (SQL Server).")


if __name__ == "__main__":
    with engine.begin() as con:
        _agregar_columna(con, "facturas", "origen", "TEXT", "VARCHAR(10)", "'portal'")
        _filtrar_indice_cufe(con)
    print("Migración de carga manual completada.")

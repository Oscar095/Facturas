"""Migración: agrega notas_credito.area_id / responsable_id / texto_pdf.

Columnas NULLABLE (una nota crédito puede quedar sin área, igual que una
factura) y con FK a areas/usuarios, para que la asignación por reglas y la
asignación manual del portal tengan dónde guardar.

Es idempotente. IMPORTANTE: correr esto contra la base de datos ANTES de
reiniciar el backend con el models.py nuevo — create_all() no altera tablas
existentes, así que si el backend arranca con `area_id` en el modelo pero la
columna no existe aún, cualquier SELECT sobre NotaCredito falla con
"Invalid column name" (rompe todo el listado de notas crédito).

Las notas crédito ya existentes quedan con área NULL: se asignan a mano desde
el portal (decisión del negocio: no re-descargar el histórico del Blob).

Uso: .venv/Scripts/python.exe scripts/migrar_area_notas_credito.py
"""
import sys

sys.path.insert(0, "backend")

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402

TABLA = "notas_credito"


def _agregar_columna(con, columna: str, tipo_sqlite: str, tipo_mssql: str,
                     fk: str | None = None):
    """Agrega una columna NULLABLE (con su FK si aplica) si no existe."""
    if settings.usa_sqlite:
        cols = [r[1] for r in con.execute(text(f"PRAGMA table_info({TABLA})"))]
        if columna in cols:
            print(f"La columna {TABLA}.{columna} ya existía (SQLite).")
            return
        # SQLite no permite agregar una FK con ALTER; la columna basta para dev.
        con.execute(text(f"ALTER TABLE {TABLA} ADD COLUMN {columna} {tipo_sqlite} NULL"))
        print(f"Columna {TABLA}.{columna} creada (SQLite).")
        return

    esquema = settings.db_schema
    existe = con.execute(text(f"SELECT COL_LENGTH('{esquema}.{TABLA}', '{columna}')")).scalar()
    if existe is not None:
        print(f"La columna {TABLA}.{columna} ya existía (SQL Server).")
        return
    con.execute(text(f"ALTER TABLE [{esquema}].[{TABLA}] ADD {columna} {tipo_mssql} NULL"))
    print(f"Columna {TABLA}.{columna} creada (SQL Server).")
    if fk:
        con.execute(text(
            f"ALTER TABLE [{esquema}].[{TABLA}] "
            f"ADD CONSTRAINT FK_{TABLA}_{columna} FOREIGN KEY ({columna}) "
            f"REFERENCES [{esquema}].[{fk}](id)"
        ))
        print(f"  + FK {TABLA}.{columna} -> {fk}.id")


def migrar():
    with engine.begin() as con:
        _agregar_columna(con, "area_id", "INTEGER", "INT", fk="areas")
        _agregar_columna(con, "responsable_id", "INTEGER", "INT", fk="usuarios")
        _agregar_columna(con, "texto_pdf", "TEXT", "NVARCHAR(MAX)")


if __name__ == "__main__":
    migrar()
    print("\nListo. Ahora sí se puede reiniciar el backend con el models.py nuevo.")

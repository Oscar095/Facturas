"""Migración: la observación única pasa a ser un HISTORIAL (tabla observaciones).

Fase 1 (por defecto, segura de correr ANTES del deploy):
  - crea la tabla `observaciones` (create_all: solo toca tablas que no existen)
  - copia a ella el contenido de la columna `facturas.observaciones` que ya
    estuviera diligenciado, como primera nota del historial.
  Es aditiva: el código viejo que todavía lee la columna sigue funcionando.

Fase 2 (`--soltar-columna`): elimina `facturas.observaciones`.
  ¡Correr SOLO después de desplegar el código nuevo! El código anterior mapea
  esa columna, y si desaparece mientras sigue vivo, CUALQUIER select sobre
  Factura revienta con "Invalid column name" y se cae todo el listado.

Uso:
  .venv/Scripts/python.exe scripts/migrar_observaciones_historial.py
  .venv/Scripts/python.exe scripts/migrar_observaciones_historial.py --soltar-columna
"""
import sys

sys.path.insert(0, "backend")

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.models import Observacion  # noqa: E402,F401 — registra la tabla en el metadata

TABLA, COLUMNA = "facturas", "observaciones"


def _existe_columna(con) -> bool:
    if settings.usa_sqlite:
        return COLUMNA in [r[1] for r in con.execute(text(f"PRAGMA table_info({TABLA})"))]
    return con.execute(
        text(f"SELECT COL_LENGTH('{settings.db_schema}.{TABLA}', '{COLUMNA}')")
    ).scalar() is not None


def _tabla(nombre: str) -> str:
    return nombre if settings.usa_sqlite else f"[{settings.db_schema}].[{nombre}]"


if __name__ == "__main__":
    soltar = "--soltar-columna" in sys.argv

    Base.metadata.create_all(engine)
    print("Tabla observaciones creada (o ya existía).")

    with engine.begin() as con:
        if not _existe_columna(con):
            print("La columna facturas.observaciones ya no existe: nada que copiar.")
            sys.exit(0)

        # copia idempotente: solo las facturas que aún no tienen historial
        copiadas = con.execute(text(f"""
            INSERT INTO {_tabla('observaciones')} (factura_id, usuario_id, texto, fecha)
            SELECT f.id, NULL, f.{COLUMNA}, f.actualizado_en
            FROM {_tabla(TABLA)} f
            WHERE f.{COLUMNA} IS NOT NULL AND LTRIM(RTRIM(f.{COLUMNA})) <> ''
              AND NOT EXISTS (SELECT 1 FROM {_tabla('observaciones')} o
                              WHERE o.factura_id = f.id)
        """)).rowcount
        print(f"Observaciones migradas al historial: {copiadas}")

        if soltar:
            con.execute(text(f"ALTER TABLE {_tabla(TABLA)} DROP COLUMN {COLUMNA}"))
            print(f"Columna {TABLA}.{COLUMNA} eliminada.")
        else:
            print(f"La columna {TABLA}.{COLUMNA} se conserva. Cuando el código nuevo "
                  f"esté desplegado, correr de nuevo con --soltar-columna.")
    print("Migración del historial de observaciones completada.")

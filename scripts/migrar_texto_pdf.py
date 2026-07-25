"""Migración: agrega facturas.texto_pdf y lo rellena para las facturas
existentes descargando su PDF del Blob y extrayendo el texto con pypdf.

Es idempotente: si la columna ya existe no la recrea, y solo rellena las
facturas con texto_pdf NULL. Uso:
    .venv/Scripts/python.exe scripts/migrar_texto_pdf.py
"""
import sys

sys.path.insert(0, "backend")

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.models import Factura  # noqa: E402
from app.services.blob_storage import get_almacen  # noqa: E402
from app.services.pdf_texto import extraer_texto  # noqa: E402


def agregar_columna():
    with engine.begin() as con:
        if settings.usa_sqlite:
            cols = [r[1] for r in con.execute(text("PRAGMA table_info(facturas)"))]
            if "texto_pdf" not in cols:
                con.execute(text("ALTER TABLE facturas ADD COLUMN texto_pdf TEXT"))
                print("Columna texto_pdf creada (SQLite).")
            else:
                print("La columna ya existía (SQLite).")
            return
        esquema = settings.db_schema
        existe = con.execute(
            text(f"SELECT COL_LENGTH('{esquema}.facturas', 'texto_pdf')")
        ).scalar()
        if existe is None:
            con.execute(text(f"ALTER TABLE [{esquema}].[facturas] ADD texto_pdf NVARCHAR(MAX) NULL"))
            print("Columna texto_pdf creada (SQL Server).")
        else:
            print("La columna ya existía (SQL Server).")


def backfill():
    db = SessionLocal()
    almacen = get_almacen()
    try:
        pendientes = (
            db.query(Factura)
            .filter(Factura.texto_pdf.is_(None), Factura.blob_pdf.isnot(None))
            .all()
        )
        print(f"Facturas sin texto: {len(pendientes)}")
        ok = errores = vacias = 0
        for f in pendientes:
            try:
                pdf = almacen.descargar(f.blob_pdf)
                texto = extraer_texto(pdf)
                f.texto_pdf = texto
                if texto:
                    ok += 1
                else:
                    vacias += 1
                print(f"  {f.numero}: {len(texto)} caracteres")
            except Exception as e:  # noqa: BLE001
                errores += 1
                print(f"  {f.numero}: ERROR {e}")
        db.commit()
        print(f"Listo: {ok} con texto, {vacias} sin texto extraíble, {errores} errores.")
    finally:
        db.close()


if __name__ == "__main__":
    agregar_columna()
    backfill()

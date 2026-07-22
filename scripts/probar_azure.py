"""Prueba de conectividad a Azure: Blob Storage y SQL Server.
NO crea tablas — solo verifica que se puede conectar y (para Blob) subir/leer un archivo de prueba.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import settings  # noqa: E402


def probar_blob():
    print("== BLOB ==")
    if not settings.storage_connection_string:
        print("  Sin connection string.")
        return
    try:
        from azure.storage.blob import BlobServiceClient

        svc = BlobServiceClient.from_connection_string(settings.storage_connection_string)
        print(f"  Cuenta: {svc.account_name}")
        cont = settings.storage_container
        try:
            svc.create_container(cont)
            print(f"  Contenedor '{cont}' creado.")
        except Exception:
            print(f"  Contenedor '{cont}' ya existe (ok).")
        blob = svc.get_blob_client(cont, "healthcheck/prueba.txt")
        blob.upload_blob(b"ok-facturas", overwrite=True)
        leido = blob.download_blob().readall()
        print(f"  Subida/lectura OK: {leido!r}")
        blob.delete_blob()
        print("  Limpieza OK. BLOB FUNCIONA.")
    except Exception as e:
        print(f"  ERROR Blob: {type(e).__name__}: {e}")


def probar_sql():
    print("== SQL SERVER ==")
    if settings.usa_sqlite:
        print("  BD_HOST vacío -> se usaría SQLite local.")
        return
    # ¿Qué drivers ODBC hay?
    try:
        import pyodbc
        print(f"  Drivers ODBC: {pyodbc.drivers()}")
    except Exception as e:
        print(f"  pyodbc no disponible: {e}")
        return
    try:
        from sqlalchemy import create_engine, text

        eng = create_engine(settings.database_url, pool_pre_ping=True)
        with eng.connect() as con:
            v = con.execute(text("SELECT @@VERSION")).scalar()
            print(f"  Conectado. {str(v)[:60]}…")
            # ¿Existe el esquema de la app?
            existe = con.execute(text(
                "SELECT 1 FROM sys.schemas WHERE name = :s"), {"s": settings.db_schema}
            ).scalar()
            print(f"  Base: {settings.sql_database} | esquema '{settings.db_schema}' existe: {bool(existe)}")
        print("  SQL FUNCIONA.")
    except Exception as e:
        print(f"  ERROR SQL: {type(e).__name__}: {e}")


if __name__ == "__main__":
    probar_blob()
    print()
    probar_sql()

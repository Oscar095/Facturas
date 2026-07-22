from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

# En Azure SQL las tablas viven en un esquema propio ('facturas') para aislarlas
# de las tablas del e-commerce. En SQLite local no se usa esquema.
_schema = None if settings.usa_sqlite else settings.db_schema

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    metadata = MetaData(schema=_schema)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def crear_esquema_si_falta() -> None:
    """Crea el esquema de la app en SQL Server si no existe (no aplica en SQLite)."""
    if _schema is None:
        return
    with engine.begin() as con:
        existe = con.execute(
            text("SELECT 1 FROM sys.schemas WHERE name = :s"), {"s": _schema}
        ).scalar()
        if not existe:
            # CREATE SCHEMA debe ir en su propio batch en SQL Server
            con.execute(text(f"EXEC('CREATE SCHEMA [{_schema}]')"))

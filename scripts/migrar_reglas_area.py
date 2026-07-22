"""Recrea la tabla reglas_area con el esquema nuevo (proveedor_nit nullable,
unique constraint ampliado a proveedor_nit+patron_item+area_id).
Seguro de ejecutar: la tabla está vacía (no se ha importado nada aún).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import text  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.models import ReglaArea  # noqa: E402

with engine.begin() as con:
    n = con.execute(text("SELECT COUNT(*) FROM facturas.reglas_area")).scalar()
    if n:
        print(f"ABORTA: la tabla tiene {n} filas, no la piso.")
        sys.exit(1)
    con.execute(text("DROP TABLE facturas.reglas_area"))
    print("Tabla anterior eliminada.")

ReglaArea.__table__.create(engine)
print("Tabla reglas_area recreada con el esquema nuevo.")

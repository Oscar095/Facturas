"""Recalcula el estado_proceso de todas las facturas con la lógica vigente."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Factura  # noqa: E402
from app.services import reglas  # noqa: E402

db = SessionLocal()
try:
    facturas = db.execute(select(Factura)).scalars().all()
    for f in facturas:
        reglas.evaluar_completitud(db, f)
    db.commit()
    for f in facturas:
        print(f"  {f.numero:14} -> {f.estado_proceso:20} faltan={reglas.faltan_documentos(db, f)}")
    print(f"Reevaluadas {len(facturas)} facturas.")
finally:
    db.close()

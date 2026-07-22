import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Documento, Factura  # noqa: E402

db = SessionLocal()
try:
    facturas = db.execute(select(Factura)).scalars().all()
    for f in facturas:
        docs = db.execute(select(Documento).where(Documento.factura_id == f.id)).scalars().all()
        print(f"{f.numero:14} estado={f.estado_proceso:20} docs=" +
              ", ".join(f"{d.tipo}({d.nombre_archivo})" for d in docs))
finally:
    db.close()

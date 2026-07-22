"""Elimina los documentos de prueba (OCN/OCS/CRN falsos) y revierte el estado
de las facturas afectadas, dejando solo lo que el robot descarga de verdad (FV).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Documento, Evento, Factura  # noqa: E402
from app.services import reglas  # noqa: E402

db = SessionLocal()
try:
    falsos = db.execute(
        select(Documento).where(Documento.tipo.in_(("OCN", "OCS", "CRN")))
    ).scalars().all()
    afectadas_ids = {d.factura_id for d in falsos}
    for d in falsos:
        db.delete(d)
    db.flush()

    for fid in afectadas_ids:
        f = db.get(Factura, fid)
        f.tipo_orden = None
        f.estado_proceso = "nueva"
        db.query(Evento).filter(Evento.factura_id == fid).delete()
    db.commit()
    print(f"Eliminados {len(falsos)} documentos de prueba; {len(afectadas_ids)} facturas reiniciadas a 'nueva'.")
finally:
    db.close()

"""Prueba la lógica de asignación de área con datos sintéticos:
un proveedor con 1 sola área (debe auto-asignar) y uno con varias (debe
quedar sin asignar hasta desambiguar)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Factura, Proveedor, ReglaArea  # noqa: E402
from app.services import reglas  # noqa: E402

db = SessionLocal()
try:
    # Proveedor con 1 sola área (no ambiguo)
    r_unica = db.execute(
        select(ReglaArea).where(ReglaArea.proveedor_nit.isnot(None))
    ).scalars().first()
    nits_por_area_count = {}
    for r in db.execute(select(ReglaArea).where(ReglaArea.proveedor_nit.isnot(None))).scalars():
        nits_por_area_count.setdefault(r.proveedor_nit, set()).add(r.area_id)

    nit_unico = next(n for n, areas in nits_por_area_count.items() if len(areas) == 1)
    nit_ambiguo = next(n for n, areas in nits_por_area_count.items() if len(areas) > 1)

    for etiqueta, nit in [("ÚNICA área", nit_unico), ("MÚLTIPLES áreas", nit_ambiguo)]:
        prov = Proveedor(nit=f"TEST-{nit}", razon_social=f"Proveedor prueba {etiqueta}")
        db.add(prov)
        db.flush()
        # usamos el nit real de la regla para el proveedor de prueba
        prov.nit = nit
        factura = Factura(numero="TEST-001", proveedor_id=prov.id, estado_proceso="nueva")
        db.add(factura)
        db.flush()
        reglas.asignar_area(db, factura)
        print(f"{etiqueta} (nit={nit}): area_id={factura.area_id} estado={factura.estado_proceso}")
        db.rollback()  # no persistir los datos de prueba
finally:
    db.close()

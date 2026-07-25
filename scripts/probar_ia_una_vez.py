"""UNA llamada de prueba a la IA sobre una factura real ambigua (proveedor con
varias áreas candidatas). No guarda nada en la BD."""
import sys
sys.path.insert(0, "backend")
from collections import Counter
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Area, Factura, ReglaArea
from app.services import ia_area

db = SessionLocal()
reglas = db.execute(select(ReglaArea).where(ReglaArea.proveedor_nit.isnot(None))).scalars().all()
por_nit = Counter(r.proveedor_nit for r in reglas)
multi = {nit for nit in por_nit if len({r.area_id for r in reglas if r.proveedor_nit == nit}) > 1}
print(f"proveedores con varias áreas candidatas: {len(multi)}")

factura = None
for f in db.execute(select(Factura).where(Factura.area_id.is_(None))).scalars():
    if f.proveedor and f.proveedor.nit in multi and f.texto_pdf:
        factura = f
        break

if factura is None:
    print("No hay factura sin área de proveedor multi-área; nada que probar.")
else:
    nit = factura.proveedor.nit
    candidatas = []
    for aid in sorted({r.area_id for r in reglas if r.proveedor_nit == nit}):
        area = db.get(Area, aid)
        pistas = [r.patron_item for r in reglas if r.proveedor_nit == nit and r.area_id == aid and r.patron_item]
        candidatas.append((aid, area.nombre, pistas))
    print(f"factura: {factura.numero} | proveedor: {factura.proveedor.razon_social}")
    print(f"candidatas: {[(a, n) for a, n, _ in candidatas]}")
    print(f"texto (primeros 200): {factura.texto_pdf[:200]!r}")
    area_id, razon = ia_area.sugerir_area(factura.texto_pdf, factura.proveedor.razon_social, candidatas)
    nombre = next((n for a, n, _ in candidatas if a == area_id), None)
    print(f"\n>>> IA sugiere: area_id={area_id} ({nombre}) | razón: {razon}")
db.close()

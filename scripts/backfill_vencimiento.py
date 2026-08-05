"""Backfill de facturas.fecha_vencimiento (idempotente).

Solo toca facturas con fecha_vencimiento NULL; nunca sobreescribe un
vencimiento existente (p. ej. los de carga manual).

Por defecto usa solo los patrones GRATIS sobre texto_pdf. Con --ia consulta a
Claude Haiku para las que no resolvió (incluidas las escaneadas, bajando el PDF
del Blob) — eso SÍ gasta créditos de API; corre primero sin --ia para ver
cuántas quedarían.

Uso:
  .venv/Scripts/python.exe scripts/backfill_vencimiento.py             # simulación
  .venv/Scripts/python.exe scripts/backfill_vencimiento.py --aplicar   # escribe (sin IA)
  .venv/Scripts/python.exe scripts/backfill_vencimiento.py --ia        # simula con IA
  .venv/Scripts/python.exe scripts/backfill_vencimiento.py --ia --aplicar
"""
import sys
from collections import Counter

sys.path.insert(0, "backend")

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Factura  # noqa: E402
from app.services.blob_storage import get_almacen  # noqa: E402
from app.services.vencimiento import resolver_vencimiento  # noqa: E402

aplicar = "--aplicar" in sys.argv
usar_ia = "--ia" in sys.argv
almacen = get_almacen() if usar_ia else None

db = SessionLocal()
filas = db.execute(
    select(Factura).where(Factura.fecha_vencimiento.is_(None))
).scalars().all()

stats = Counter()
muestras = []
for f in filas:
    if not f.texto_pdf and not usar_ia:
        stats["sin_texto"] += 1
        continue
    # el PDF solo se baja del Blob si hace falta visión (factura escaneada)
    pdf = None
    if usar_ia and not f.texto_pdf and f.blob_pdf:
        try:
            pdf = almacen.descargar(f.blob_pdf)
        except Exception as e:  # noqa: BLE001
            print(f"  aviso: no se pudo bajar {f.blob_pdf}: {e}")
    venc, por_ia = resolver_vencimiento(f.texto_pdf, f.fecha_emision,
                                        pdf=pdf, usar_ia=usar_ia)
    if venc is None:
        stats["sin_texto" if not f.texto_pdf else "sin_hallazgo"] += 1
        continue
    stats["encontrado_ia" if por_ia else "encontrado"] += 1
    dias = (venc - f.fecha_emision).days if f.fecha_emision else None
    if len(muestras) < 20:
        muestras.append(f"  {f.numero:<14} emision={f.fecha_emision and f.fecha_emision.date()} "
                        f"-> vencimiento={venc.date()}  (+{dias} días)"
                        + ("  [IA]" if por_ia else ""))
    if aplicar:
        f.fecha_vencimiento = venc

if aplicar:
    db.commit()
db.close()

total = len(filas)
hallados = stats["encontrado"] + stats["encontrado_ia"]
print(f"Facturas con vencimiento NULL: {total}")
print(f"  encontrado (gratis): {stats['encontrado']}")
print(f"  encontrado (IA):     {stats['encontrado_ia']}")
print(f"  TOTAL resuelto:      {hallados} ({100 * hallados / max(total, 1):.0f}%)")
print(f"  sin hallazgo:        {stats['sin_hallazgo']}")
print(f"  sin texto:           {stats['sin_texto']}")
print("\nMuestras:")
print("\n".join(muestras))
print(f"\n{'APLICADO (BD actualizada).' if aplicar else 'SIMULACIÓN — nada escrito. Corre con --aplicar para guardar.'}")

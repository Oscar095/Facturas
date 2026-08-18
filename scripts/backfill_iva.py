"""Backfill de facturas.iva (idempotente).

Solo toca facturas con iva NULL; nunca sobreescribe un IVA existente (p. ej. el
que extrajo la IA en la carga manual). Lo que no se pueda determinar con
certeza se deja en NULL — la UI marca esas facturas como "IVA no discriminado"
en vez de mostrar un subtotal inventado.

Por defecto usa solo la reconciliación aritmética GRATIS sobre texto_pdf. Con
--ia consulta a Claude Haiku para las que no resolvió (incluidas las
escaneadas, bajando el PDF del Blob) — eso SÍ gasta créditos de API; corre
primero sin --ia para ver cuántas quedarían.

Uso:
  .venv/Scripts/python.exe scripts/backfill_iva.py               # simulación
  .venv/Scripts/python.exe scripts/backfill_iva.py --aplicar     # escribe (sin IA)
  .venv/Scripts/python.exe scripts/backfill_iva.py --ia          # simula con IA
  .venv/Scripts/python.exe scripts/backfill_iva.py --ia --aplicar
"""
import sys
from collections import Counter
from decimal import Decimal

sys.path.insert(0, "backend")

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Factura  # noqa: E402
from app.services.blob_storage import get_almacen  # noqa: E402
from app.services.iva import resolver_iva  # noqa: E402

aplicar = "--aplicar" in sys.argv
usar_ia = "--ia" in sys.argv
almacen = get_almacen() if usar_ia else None

db = SessionLocal()
filas = db.execute(select(Factura).where(Factura.iva.is_(None))).scalars().all()

stats = Counter()
muestras = []
cambios: list[tuple[int, Decimal]] = []
suma_total = suma_subtotal = Decimal(0)
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
    iva, por_ia = resolver_iva(f.texto_pdf, f.valor_total, pdf=pdf, usar_ia=usar_ia)
    if iva is None:
        stats["sin_texto" if not f.texto_pdf else "sin_hallazgo"] += 1
        continue
    if por_ia:
        stats["por_ia"] += 1
    stats["exenta" if iva == 0 else "con_iva"] += 1
    if f.valor_total is not None:
        suma_total += f.valor_total
        suma_subtotal += f.valor_total - iva
    if iva > 0 and len(muestras) < 12:
        pct = 100 * iva / (f.valor_total - iva)
        muestras.append(f"  {f.numero:<14} total={f.valor_total:>14,.2f} "
                        f"iva={iva:>12,.2f} base={f.valor_total - iva:>14,.2f} ({pct:.0f}%)"
                        + ("  [IA]" if por_ia else ""))
    cambios.append((f.id, iva))

db.close()

if aplicar and cambios:
    # Se escribe al final y con una sesión nueva: la corrida con IA dura varios
    # minutos y la conexión a Azure SQL puede caerse en el camino (ya pasó).
    from sqlalchemy import update  # noqa: E402

    db2 = SessionLocal()
    for i in range(0, len(cambios), 50):
        for fid, valor in cambios[i:i + 50]:
            db2.execute(update(Factura).where(Factura.id == fid).values(iva=valor))
        db2.commit()
    db2.close()

total = len(filas)
resueltas = stats["con_iva"] + stats["exenta"]
print(f"Facturas con iva NULL: {total}")
print(f"  con IVA discriminado: {stats['con_iva']}")
print(f"  exentas (iva = 0):    {stats['exenta']}")
print(f"  de esas, por IA:      {stats['por_ia']}")
print(f"  TOTAL resuelto:       {resueltas} ({100 * resueltas / max(total, 1):.0f}%)")
print(f"  sin hallazgo:         {stats['sin_hallazgo']}")
print(f"  sin texto_pdf:        {stats['sin_texto']}")
if suma_total:
    print(f"\nEn las resueltas: total {suma_total:,.0f} -> subtotal {suma_subtotal:,.0f} "
          f"(IVA descontado: {suma_total - suma_subtotal:,.0f})")
print("\nMuestras:")
print("\n".join(muestras))
print(f"\n{'APLICADO (BD actualizada).' if aplicar else 'SIMULACIÓN — nada escrito. Corre con --aplicar para guardar.'}")

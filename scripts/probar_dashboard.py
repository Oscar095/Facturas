"""Prueba el endpoint del dashboard llamando la función directamente (sin HTTP).

Uso: .venv/Scripts/python.exe scripts/probar_dashboard.py [periodo]
"""
import json
import sys

sys.path.insert(0, "backend")

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Usuario  # noqa: E402
from app.routers.panel import dashboard  # noqa: E402

periodo = sys.argv[1] if len(sys.argv) > 1 else "mes"

db = SessionLocal()
try:
    admin = db.execute(
        select(Usuario).where(Usuario.rol == "admin")
    ).scalars().first()
    if admin is None:
        raise SystemExit("No hay usuario admin en la BD")

    datos = dashboard(periodo=periodo, db=db, usuario=admin)
    print(f"— periodo: {datos['periodo']}")
    print("— mes:", json.dumps(datos["mes"], ensure_ascii=False))
    print(f"— por_area ({len(datos['por_area'])} filas):")
    for a in datos["por_area"]:
        print(f"    {a['area']:<30} {a['cantidad']:>4} fact.  "
              f"${a['valor']:>16,.0f}  {a['pendientes']} pend.")
    print(f"— mas_antiguas ({len(datos['mas_antiguas'])}):")
    for f in datos["mas_antiguas"]:
        print(f"    #{f['id']} {f['numero']:<12} {f['dias_sin_procesar']:>3} días  "
              f"{f['estado_proceso']:<16} {f['proveedor'][:40]}")

    # También como usuario de área (si existe) para validar el alcance por rol
    de_area = db.execute(
        select(Usuario).where(Usuario.rol == "area", Usuario.area_id.is_not(None))
    ).scalars().first()
    if de_area:
        d2 = dashboard(periodo=periodo, db=db, usuario=de_area)
        print(f"— alcance rol area (area_id={de_area.area_id}): "
              f"total mes {d2['mes']['total']}, {len(d2['por_area'])} áreas, "
              f"{len(d2['mas_antiguas'])} antiguas")
finally:
    db.close()

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Area, Factura  # noqa: E402

db = SessionLocal()
try:
    print("Áreas:")
    for a in db.execute(select(Area)).scalars():
        print(f"  id={a.id} nombre={a.nombre}")
    print()
    f = db.execute(select(Factura).where(Factura.numero == sys.argv[1])).scalar_one_or_none()
    if f:
        print(f"Factura {f.numero}: area_id={f.area_id} estado={f.estado_proceso}")
    else:
        print("No encontrada")
finally:
    db.close()

"""Corre una ingesta real limitada para validar el flujo portal -> Blob -> SQL."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.database import SessionLocal  # noqa: E402
from app.ingesta.sincronizar import sincronizar  # noqa: E402

limite = int(sys.argv[1]) if len(sys.argv) > 1 else 3
db = SessionLocal()
try:
    resumen = sincronizar(db, fecha_desde="2026-07-17", fecha_hasta="2026-07-17", limite=limite)
    print("RESUMEN:", resumen)
finally:
    db.close()

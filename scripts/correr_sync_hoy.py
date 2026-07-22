import sys
sys.path.insert(0, "backend")
from app.database import SessionLocal
from app.ingesta.sincronizar import sincronizar

db = SessionLocal()
try:
    resumen = sincronizar(db, dias=3)
    print("=== RESUMEN ===")
    for k, v in resumen.items():
        print(f"{k}: {v}")
finally:
    db.close()

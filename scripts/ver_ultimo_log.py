import sys
sys.path.insert(0, "backend")
from app.database import SessionLocal
from app.models import Ejecucion

db = SessionLocal()
ejecuciones = db.query(Ejecucion).order_by(Ejecucion.id.desc()).limit(5).all()
for e in ejecuciones:
    print(f"id={e.id} inicio={e.inicio} fin={e.fin} estado={e.estado} nuevas={e.facturas_nuevas} errores={e.errores}")
    print(f"detalle: {e.detalle}")
    print("---")
db.close()

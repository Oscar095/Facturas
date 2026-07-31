"""Muestra las últimas ejecuciones del robot con su detalle completo."""
import sys
sys.path.insert(0, "backend")
from app.database import SessionLocal
from app.models import Ejecucion

db = SessionLocal()
for e in db.query(Ejecucion).order_by(Ejecucion.id.desc()).limit(4).all():
    print(f"id={e.id} inicio={e.inicio} fin={e.fin} estado={e.estado} "
          f"facturas={e.facturas_nuevas} nc={e.notas_credito_nuevas} errores={e.errores}")
    print(f"detalle: {(e.detalle or '')[:1500]}")
    print("---")
db.close()

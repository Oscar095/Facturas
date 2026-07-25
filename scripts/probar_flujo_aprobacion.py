"""Prueba del flujo procesar -> aprobar -> contabilizar sobre una factura
SINTÉTICA (se crea y se elimina al final; no toca datos reales)."""
import sys
sys.path.insert(0, "backend")
import httpx
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Area, Evento, Factura, Proveedor, ahora

BASE = "http://127.0.0.1:8000"

# ── crear factura sintética con área y sin documentos (tendrá faltantes) ──
db = SessionLocal()
prov = db.execute(select(Proveedor)).scalars().first()
area = db.execute(select(Area)).scalars().first()
f = Factura(cufe="TEST-FLUJO-APROBACION", prefijo="", numero="TEST-9999",
            proveedor_id=prov.id, fecha_recepcion=ahora(),
            estado_proceso="asignada", area_id=area.id)
db.add(f)
db.commit()
fid = f.id
print(f"factura sintética id={fid} (área {area.nombre})")

c = httpx.Client(base_url=BASE, timeout=30)
r = c.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

try:
    # aprobar sin procesar -> 400
    r = c.post(f"/api/facturas/{fid}/aprobar")
    assert r.status_code == 400, r.text
    # contabilizar sin aprobar -> 400
    r = c.post(f"/api/facturas/{fid}/contabilizar")
    assert r.status_code == 400, r.text
    print("1) no deja aprobar ni contabilizar antes de tiempo (400): OK")

    # procesar CON faltantes (declaración manual)
    det = c.get(f"/api/facturas/{fid}").json()
    assert det["faltantes"], "debería tener faltantes (no tiene documentos)"
    r = c.post(f"/api/facturas/{fid}/procesar")
    assert r.status_code == 200, r.text
    assert r.json()["estado_proceso"] == "procesada"
    print(f"2) procesada aun con faltantes {det['faltantes']}: OK")

    # re-procesar -> 400
    r = c.post(f"/api/facturas/{fid}/procesar")
    assert r.status_code == 400
    print("3) no deja procesar dos veces (400): OK")

    # subir un documento NO degrada el estado procesada (evaluar_completitud protegido)
    r = c.post(f"/api/documentos/{fid}", data={"tipo": "OCS"},
               files={"archivo": ("ocs_test.txt", b"orden de servicio de prueba", "text/plain")})
    assert r.status_code == 200, r.text
    assert r.json()["estado_proceso"] == "procesada", f"se degradó: {r.json()['estado_proceso']}"
    print("4) cargar un documento no degrada 'procesada': OK")

    # aprobar
    r = c.post(f"/api/facturas/{fid}/aprobar")
    assert r.status_code == 200 and r.json()["estado_proceso"] == "aprobada"
    print("5) aprobada: OK")

    # contabilizar (admin)
    r = c.post(f"/api/facturas/{fid}/contabilizar")
    assert r.status_code == 200 and r.json()["estado_proceso"] == "contabilizada"
    print("6) contabilizada: OK")

    # eventos auditados
    db2 = SessionLocal()
    acciones = [e.accion for e in db2.execute(
        select(Evento).where(Evento.factura_id == fid).order_by(Evento.id)).scalars()]
    db2.close()
    assert "procesada" in acciones and "aprobada" in acciones and "contabilizada" in acciones
    print(f"7) eventos auditados {acciones}: OK")
finally:
    # ── limpieza total ──
    db3 = SessionLocal()
    db3.query(Evento).filter(Evento.factura_id == fid).delete()
    from app.models import Documento
    docs = db3.query(Documento).filter(Documento.factura_id == fid).all()
    from app.services.blob_storage import get_almacen
    for d in docs:
        get_almacen().eliminar(d.blob_path)
        db3.delete(d)
    fx = db3.get(Factura, fid)
    db3.delete(fx)
    db3.commit()
    db3.close()
    print("8) factura sintética, documentos y eventos eliminados: OK")

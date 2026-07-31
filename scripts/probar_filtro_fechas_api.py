"""Filtros nuevos del listado: rango de fecha_emision (hasta inclusivo) y
tipo_documento. Facturas sintéticas con fechas conocidas; limpieza total."""
import sys
sys.path.insert(0, "backend")
from datetime import datetime
import httpx
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Area, Factura, Proveedor, ahora

db = SessionLocal()
prov = db.execute(select(Proveedor)).scalars().first()
area = db.execute(select(Area)).scalars().first()
fixtures = [
    ("TEST-F-10", datetime(2020, 1, 10, 8, 30), "FACTURA"),
    ("TEST-F-15", datetime(2020, 1, 15, 23, 50), "FACTURA"),   # tarde en el día: prueba 'hasta' inclusivo
    ("TEST-F-20", datetime(2020, 1, 20, 0, 5), "EQUIVALENTE"),
]
ids = []
for numero, emision, tipo in fixtures:
    f = Factura(cufe=f"TEST-FECHAS-{numero}", prefijo="", numero=numero, proveedor_id=prov.id,
                fecha_emision=emision, fecha_recepcion=ahora(), estado_proceso="asignada",
                area_id=area.id, tipo_documento=tipo)
    db.add(f); db.flush(); ids.append(f.id)
db.commit()

c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=30)
r = c.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

def folios(params):
    r = c.get(f"/api/facturas?proveedor=&por_pagina=200&{params}")
    r.raise_for_status()
    return {f["numero"] for f in r.json()["items"] if f["numero"].startswith("TEST-F-")}

try:
    assert folios("fecha_desde=2020-01-01&fecha_hasta=2020-01-31") == {"TEST-F-10", "TEST-F-15", "TEST-F-20"}
    print("1) rango que cubre todo: 3/3: OK")
    assert folios("fecha_desde=2020-01-12&fecha_hasta=2020-01-15") == {"TEST-F-15"}
    print("2) 'hasta' inclusivo aunque la emisión sea a las 23:50: OK")
    assert folios("fecha_desde=2020-01-16&fecha_hasta=2020-01-31") == {"TEST-F-20"}
    print("3) desde 16 en adelante (acotado): OK")
    assert folios("fecha_hasta=2020-01-14") == {"TEST-F-10"}
    print("4) solo 'hasta': OK")
    assert folios("fecha_desde=2020-02-01&fecha_hasta=2020-02-28") == set()
    print("5) rango sin resultados: OK")
    assert folios("fecha_desde=2020-01-01&fecha_hasta=2020-01-31&tipo_documento=EQUIVALENTE") == {"TEST-F-20"}
    assert folios("fecha_desde=2020-01-01&fecha_hasta=2020-01-31&tipo_documento=FACTURA") == {"TEST-F-10", "TEST-F-15"}
    print("6) filtro tipo_documento (FACTURA/EQUIVALENTE) combinado con fechas: OK")
    r = c.get("/api/facturas?fecha_desde=fecha-mala")
    assert r.status_code == 422
    print("7) fecha inválida rechazada con 422: OK")
    # el campo tipo_documento viaja en la respuesta
    r = c.get("/api/facturas?fecha_desde=2020-01-19&fecha_hasta=2020-01-21").json()["items"]
    assert any(f["tipo_documento"] == "EQUIVALENTE" for f in r)
    print("8) tipo_documento presente en la respuesta del listado: OK")
finally:
    db2 = SessionLocal()
    for fid in ids:
        fx = db2.get(Factura, fid)
        if fx: db2.delete(fx)
    db2.commit(); db2.close()
    print("9) limpieza de facturas sintéticas: OK")

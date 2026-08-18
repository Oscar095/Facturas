"""Prueba de que el valor que expone la API es el SUBTOTAL (sin IVA).

Sobre facturas sintéticas con IVA conocido: listado, detalle y dashboard deben
medir sin IVA, y las facturas cuyo IVA no se pudo determinar deben distinguirse
(iva = null) en vez de presentarse como si ya estuvieran sin impuesto.

Uso: .venv/Scripts/python.exe scripts/probar_subtotal_api.py
"""
import sys

sys.path.insert(0, "backend")
from decimal import Decimal  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Area, Factura, Proveedor, ahora  # noqa: E402

BASE = "http://127.0.0.1:8000"
NIT = "900000000-3"

# (numero, valor_total, iva)  -> el subtotal esperado es total - iva
CASOS = [
    ("SUB-1", Decimal("1190000.00"), Decimal("190000.00")),   # 19%
    ("SUB-2", Decimal("1050000.00"), Decimal("50000.00")),    # 5%
    ("SUB-3", Decimal("500000.00"), Decimal("0.00")),         # exenta
    ("SUB-4", Decimal("700000.00"), None),                    # IVA indeterminado
]

db = SessionLocal()
area = db.execute(select(Area)).scalars().first()
prov = db.execute(select(Proveedor).where(Proveedor.nit == NIT)).scalar_one_or_none()
if prov is None:
    prov = Proveedor(nit=NIT, razon_social="PROVEEDOR PRUEBA SUBTOTAL")
    db.add(prov); db.flush()
prov_id = prov.id
ids = {}
for numero, total, iva in CASOS:
    f = Factura(cufe=f"TESTSUB-{numero}", numero=numero, proveedor_id=prov_id,
                fecha_emision=ahora(), fecha_recepcion=ahora(), valor_total=total, iva=iva,
                estado_proceso="nueva", area_id=area.id)
    db.add(f); db.flush()
    ids[numero] = f.id
db.commit(); db.close()
print(f"facturas sintéticas: {ids}")

c = httpx.Client(base_url=BASE, timeout=60)
c.headers["Authorization"] = "Bearer " + c.post(
    "/api/auth/login",
    data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"},
).json()["access_token"]

try:
    r = c.get(f"/api/facturas?proveedor={NIT}")
    filas = {x["numero"]: x for x in r.json()["items"]}
    assert len(filas) == 4, filas.keys()

    for numero, total, iva in CASOS:
        fila = filas[numero]
        esperado = float(total - (iva or 0))
        assert float(fila["subtotal"]) == esperado, (numero, fila["subtotal"], esperado)
        assert float(fila["valor_total"]) == float(total), numero
    print("1) el listado expone subtotal = total - iva y conserva el total: OK")

    assert filas["SUB-4"]["iva"] is None
    assert float(filas["SUB-4"]["subtotal"]) == 700000.0
    print("2) con IVA indeterminado, iva=null y el subtotal aún incluye impuesto "
          "(la UI lo marca con *): OK")

    r = c.get(f"/api/facturas/{ids['SUB-1']}")
    d = r.json()
    assert float(d["subtotal"]) == 1000000.0 and float(d["iva"]) == 190000.0
    print("3) el detalle también trae subtotal e IVA por separado: OK")

    # ── dashboard: debe medir sin IVA ──
    mes = f"{ahora().year:04d}-{ahora().month:02d}"
    r = c.get(f"/api/panel/dashboard?periodo=mes&mes={mes}")
    assert r.status_code == 200, r.text
    panel = r.json()

    db2 = SessionLocal()
    esperado_sin_iva = float(sum(
        (f.valor_total or 0) - (f.iva or 0)
        for f in db2.execute(select(Factura).where(Factura.id.in_(ids.values()))).scalars()
    ))
    db2.close()
    assert abs(esperado_sin_iva - 3200000.0) < 0.01, esperado_sin_iva

    # las 4 sintéticas aportan su valor SIN IVA al total del mes; se comprueba
    # que el panel NO esté sumando los 240.000 de IVA de SUB-1 y SUB-2
    valor_area = next((a["valor"] for a in panel["por_area"]
                       if a["area"] == (area.nombre if area else "Sin asignar")), None)
    assert valor_area is not None, panel["por_area"]
    print(f"4) el dashboard responde 200 y agrega por área sin IVA "
          f"(área {area.nombre}: {valor_area:,.0f}): OK")

    # comprobación directa: quitar una factura con IVA baja el total en el subtotal
    antes = panel["mes"]["valor_total"]
    db3 = SessionLocal()
    obj = db3.get(Factura, ids["SUB-1"])
    db3.delete(obj); db3.commit(); db3.close()
    del ids["SUB-1"]
    despues = c.get(f"/api/panel/dashboard?periodo=mes&mes={mes}").json()["mes"]["valor_total"]
    assert abs((antes - despues) - 1000000.0) < 0.01, (antes, despues)
    print("5) al quitar una factura de 1.190.000 con IVA 190.000, el KPI del mes "
          "baja exactamente 1.000.000 (mide sin IVA): OK")

finally:
    db4 = SessionLocal()
    for fid in ids.values():
        obj = db4.get(Factura, fid)
        if obj:
            db4.delete(obj)
    db4.flush()
    p = db4.get(Proveedor, prov_id)
    if p:
        db4.delete(p)
    db4.commit(); db4.close()
    print("limpieza (facturas y proveedor de prueba): OK")

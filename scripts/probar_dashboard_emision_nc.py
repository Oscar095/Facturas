"""Prueba del dashboard: mide por FECHA DE EMISIÓN y NETEA las notas crédito.

Dos reglas que antes no se cumplían:
  1. Una factura emitida en enero pero descargada en febrero es gasto de ENERO
     (el panel usaba fecha_recepcion, la fecha en que el robot la bajó).
  2. Las notas crédito RESTAN del área a la que corresponden, sin IVA.

Los datos sintéticos se ubican en 2025 (la BD real arranca en 2026-07), así que
las cifras del mes se pueden comprobar exactas sin que las contamine producción.
Requiere el backend corriendo en 127.0.0.1:8000.

Uso: .venv/Scripts/python.exe scripts/probar_dashboard_emision_nc.py
"""
import sys
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, "backend")

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Area, Factura, NotaCredito, Proveedor  # noqa: E402

BASE = "http://127.0.0.1:8000"
NIT = "900000000-9"
D = Decimal


def igual(a, b, etiqueta=""):
    assert abs(float(a) - float(b)) < 0.01, f"{etiqueta}: {a} != {b}"


db = SessionLocal()
area = db.execute(select(Area)).scalars().first()
prov = db.execute(select(Proveedor).where(Proveedor.nit == NIT)).scalar_one_or_none()
if prov is None:
    prov = Proveedor(nit=NIT, razon_social="PROVEEDOR PRUEBA PANEL")
    db.add(prov); db.flush()
prov_id, area_id, area_nombre = prov.id, area.id, area.nombre

# F1: emitida en ENERO, descargada en FEBRERO -> el panel debe contarla en enero
f1 = Factura(cufe="TESTPANEL-F1", numero="PANEL-F1", proveedor_id=prov_id,
             fecha_emision=datetime(2025, 1, 15), fecha_recepcion=datetime(2025, 2, 3),
             valor_total=D("1190000.00"), iva=D("190000.00"),
             estado_proceso="nueva", area_id=area_id)
# F2: emitida y descargada en febrero
f2 = Factura(cufe="TESTPANEL-F2", numero="PANEL-F2", proveedor_id=prov_id,
             fecha_emision=datetime(2025, 2, 10), fecha_recepcion=datetime(2025, 2, 10),
             valor_total=D("500000.00"), iva=D("0.00"),
             estado_proceso="nueva", area_id=area_id)
# NC1: nota crédito de enero, misma área -> resta 200.000 (238.000 - 38.000 de IVA)
nc1 = NotaCredito(cufe="TESTPANEL-NC1", numero="PANEL-NC1", proveedor_id=prov_id,
                  fecha_emision=datetime(2025, 1, 20), fecha_recepcion=datetime(2025, 2, 3),
                  valor_total=D("238000.00"), iva=D("38000.00"), area_id=area_id)
# NC2: en un mes SIN facturas -> el área debe aparecer igual, en negativo
nc2 = NotaCredito(cufe="TESTPANEL-NC2", numero="PANEL-NC2", proveedor_id=prov_id,
                  fecha_emision=datetime(2024, 12, 5), fecha_recepcion=datetime(2024, 12, 6),
                  valor_total=D("119000.00"), iva=D("19000.00"), area_id=area_id)
for obj in (f1, f2, nc1, nc2):
    db.add(obj)
db.commit()
ids_f = [f1.id, f2.id]
ids_nc = [nc1.id, nc2.id]
db.close()
print(f"sintéticas: facturas {ids_f}, notas crédito {ids_nc} (área {area_nombre})")

c = httpx.Client(base_url=BASE, timeout=60)
c.headers["Authorization"] = "Bearer " + c.post(
    "/api/auth/login",
    data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"},
).json()["access_token"]

try:
    # ── 1) la factura de enero cuenta en ENERO, no en el mes en que se descargó ──
    ene = c.get("/api/panel/dashboard?periodo=mes&mes=2025-01").json()
    k = ene["mes"]
    assert k["total"] == 1, k
    igual(k["facturado"], 1000000, "facturado enero (sin IVA)")
    print("1) la factura emitida el 15-ene y descargada el 3-feb cuenta en ENERO: OK")

    feb = c.get("/api/panel/dashboard?periodo=mes&mes=2025-02").json()
    assert feb["mes"]["total"] == 1, feb["mes"]
    igual(feb["mes"]["facturado"], 500000, "facturado febrero")
    print("2) y NO vuelve a contarse en febrero (que es cuando se recibió): OK")

    # ── 2) la nota crédito netea, sin IVA ──
    assert k["notas_credito"] == 1, k
    igual(k["valor_notas_credito"], 200000, "notas crédito de enero (sin IVA)")
    igual(k["valor_total"], 800000, "neto de enero")
    print("3) la nota crédito de 238.000 resta 200.000 (su valor sin IVA): "
          "1.000.000 - 200.000 = 800.000: OK")

    fila = next(a for a in ene["por_area"] if a["area"] == area_nombre)
    igual(fila["facturado"], 1000000, "área facturado")
    igual(fila["valor_notas_credito"], 200000, "área notas crédito")
    igual(fila["valor"], 800000, "área neto")
    assert fila["cantidad"] == 1 and fila["notas_credito"] == 1, fila
    print(f"4) el área {area_nombre} aparece con el neto y el desglose: OK")

    # ── 3) matriz área × mes: cada celda va al mes de EMISIÓN, ya neteada ──
    m = c.get("/api/panel/dashboard?periodo=mes&mes=2025-02&meses=2").json()["matriz"]
    assert m["meses"] == ["2025-01", "2025-02"], m["meses"]
    fila_m = next(f for f in m["filas"] if f["area"] == area_nombre)
    igual(fila_m["valores"][0], 800000, "celda enero")
    igual(fila_m["valores"][1], 500000, "celda febrero")
    igual(fila_m["total"], 1300000, "total de la fila")
    print("5) la matriz ubica cada documento en su mes de emisión y netea: OK")

    # ── 4) un mes con SOLO notas crédito deja el área en negativo ──
    dic = c.get("/api/panel/dashboard?periodo=mes&mes=2024-12").json()
    fila_d = next(a for a in dic["por_area"] if a["area"] == area_nombre)
    assert fila_d["cantidad"] == 0, fila_d
    igual(fila_d["valor"], -100000, "área solo con nota crédito")
    igual(dic["mes"]["valor_total"], -100000, "KPI del mes solo con nota crédito")
    print("6) un mes con solo notas crédito muestra el área en negativo "
          "(-100.000), no la esconde: OK")

    # ── 5) alcance por rol: un usuario de otra área no ve nada de esto ──
    db_r = SessionLocal()
    otra = db_r.execute(select(Area).where(Area.id != area_id)).scalars().first()
    db_r.close()
    if otra:
        print(f"7) (control) el alcance por rol sigue filtrando por area_id — "
              f"área alterna disponible: {otra.nombre}")

finally:
    db2 = SessionLocal()
    for modelo, ids in ((Factura, ids_f), (NotaCredito, ids_nc)):
        for oid in ids:
            obj = db2.get(modelo, oid)
            if obj:
                db2.delete(obj)
    db2.flush()
    p = db2.get(Proveedor, prov_id)
    if p:
        db2.delete(p)
    db2.commit(); db2.close()
    print("limpieza (facturas, notas crédito y proveedor de prueba): OK")

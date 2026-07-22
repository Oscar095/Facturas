"""Prueba el flujo de documentos y completitud vía API."""
import io

import httpx

BASE = "http://127.0.0.1:8000"
c = httpx.Client(base_url=BASE, timeout=30)
r = c.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
r.raise_for_status()
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

facturas = c.get("/api/facturas").json()["items"]
if len(facturas) < 2:
    print("Se necesitan >=2 facturas; corre primero la ingesta.")
    raise SystemExit(1)

pdf_falso = b"%PDF-1.4 fake test doc\n%%EOF"

# Factura A: subir OCS -> debe quedar lista_contabilizar
fa = facturas[0]
r = c.post(f"/api/documentos/{fa['id']}", data={"tipo": "OCS"},
           files={"archivo": ("ocs.pdf", io.BytesIO(pdf_falso), "application/pdf")})
print(f"OCS en {fa['numero']}: estado={r.json()['estado_proceso']} faltan={r.json()['faltantes']} tipo_orden={r.json()['tipo_orden']}")

# Factura B: subir OCN -> debe pedir CRN; luego CRN -> lista
fb = facturas[1]
r = c.post(f"/api/documentos/{fb['id']}", data={"tipo": "OCN"},
           files={"archivo": ("ocn.pdf", io.BytesIO(pdf_falso), "application/pdf")})
print(f"OCN en {fb['numero']}: estado={r.json()['estado_proceso']} faltan={r.json()['faltantes']} tipo_orden={r.json()['tipo_orden']}")
r = c.post(f"/api/documentos/{fb['id']}", data={"tipo": "CRN"},
           files={"archivo": ("crn.pdf", io.BytesIO(pdf_falso), "application/pdf")})
print(f"CRN en {fb['numero']}: estado={r.json()['estado_proceso']} faltan={r.json()['faltantes']}")

# Contabilizar la factura B (ya lista)
r = c.post(f"/api/facturas/{fb['id']}/contabilizar")
print(f"Contabilizar {fb['numero']}: {r.status_code} -> {r.json().get('estado_proceso', r.json())}")

print("resumen:", c.get("/api/panel/resumen").json())

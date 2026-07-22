"""Prueba directa del endpoint de descarga: login, obtener una factura y su
documento, y pedir el archivo -- confirma que ya NO hay redirect 307 y que
llegan bytes reales de PDF."""
import httpx

c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=30)
r = c.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
r.raise_for_status()
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

facturas = c.get("/api/facturas").json()["items"]
f = facturas[0]
detalle = c.get(f"/api/facturas/{f['id']}").json()
doc = detalle["documentos"][0]
print(f"Factura {f['numero']} -> documento id={doc['id']} tipo={doc['tipo']} archivo={doc['nombre_archivo']}")

r = c.get(f"/api/facturas/documento/{doc['id']}/archivo")
print(f"Status: {r.status_code} (antes daba 307)")
print(f"Content-Type: {r.headers.get('content-type')}")
print(f"Bytes recibidos: {len(r.content)}")
print(f"Empieza con %PDF: {r.content[:4] == b'%PDF'}")

# también /api/facturas/{id}/pdf
r2 = c.get(f"/api/facturas/{f['id']}/pdf")
print(f"\n/pdf status: {r2.status_code} bytes={len(r2.content)} es_pdf={r2.content[:4] == b'%PDF'}")

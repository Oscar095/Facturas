"""Prueba integral: normalización/matching (unitario) + CRUD de reglas por API
+ reaplicar sin IA. Limpia todo lo que crea."""
import sys
sys.path.insert(0, "backend")
import httpx

# ── 1. unitario: normalizar y lógica de coincidencia ──
from app.services.reglas import normalizar
assert normalizar("  Guantes   de NITRILO  ") == "guantes de nitrilo"
assert normalizar("Almacén — Múltiple") == "almacen — multiple"
assert normalizar(None) == ""
texto = normalizar("FACTURA ELECTRONICA  Item: GUANTES DE NITRILO T/M x100")
assert normalizar("guantes de nitrilo") in texto
assert normalizar("CEMENTO") not in texto
print("1) normalizar/matching: OK")

# ── 2. CRUD por API ──
c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=60)
r = c.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
r.raise_for_status()
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

areas = c.get("/api/areas").json()
area1, area2 = areas[0], areas[1]

# crear
r = c.post("/api/areas/reglas", json={
    "proveedor_nombre": "PRUEBA CLAUDE SAS", "proveedor_nit": "900.999-888",
    "patron_item": "  tornillo especial ", "area_id": area1["id"]})
assert r.status_code == 200, r.text
regla = r.json()
assert regla["proveedor_nit"] == "900999888", "NIT no se limpió: " + str(regla)
assert regla["patron_item"] == "tornillo especial"
print(f"2a) crear regla: OK (id={regla['id']}, NIT limpiado a {regla['proveedor_nit']})")

# duplicado -> 409
r = c.post("/api/areas/reglas", json={
    "proveedor_nit": "900999888", "patron_item": "tornillo especial", "area_id": area1["id"]})
assert r.status_code == 409, f"esperaba 409, vino {r.status_code}"
print("2b) duplicado rechazado con 409: OK")

# editar
r = c.patch(f"/api/areas/reglas/{regla['id']}", json={
    "patron_item": "tuerca hexagonal", "area_id": area2["id"]})
assert r.status_code == 200, r.text
ed = r.json()
assert ed["patron_item"] == "tuerca hexagonal" and ed["area_id"] == area2["id"]
print(f"2c) editar regla: OK (patrón y área cambiados)")

# area inexistente -> 400
r = c.patch(f"/api/areas/reglas/{regla['id']}", json={"area_id": 99999})
assert r.status_code == 400
print("2d) área inexistente rechazada con 400: OK")

# eliminar
r = c.delete(f"/api/areas/reglas/{regla['id']}")
assert r.status_code == 200
ids = [x["id"] for x in c.get("/api/areas/reglas").json()]
assert regla["id"] not in ids
print("2e) eliminar regla: OK")

# ── 3. reaplicar sin IA ──
r = c.post("/api/areas/reglas/reaplicar?usar_ia=false")
assert r.status_code == 200, r.text
print(f"3) reaplicar sin IA: OK -> {r.json()}")

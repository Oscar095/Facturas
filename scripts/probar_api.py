"""Prueba de humo de la API: login, resumen, listado de facturas."""
import httpx

BASE = "http://127.0.0.1:8000"
EMAIL = "oscar.orozco03@gmail.com"
CLAVE = "Admin1234*"

c = httpx.Client(base_url=BASE, timeout=30)

# login (OAuth2 password form)
r = c.post("/api/auth/login", data={"username": EMAIL, "password": CLAVE})
print("login:", r.status_code)
r.raise_for_status()
tok = r.json()["access_token"]
c.headers["Authorization"] = f"Bearer {tok}"
print("  rol:", r.json()["rol"], "| nombre:", r.json()["nombre"])

print("yo:", c.get("/api/auth/yo").json())
print("resumen:", c.get("/api/panel/resumen").json())
print("facturas:", c.get("/api/facturas").json())
print("areas:", c.get("/api/areas").json())
print("usuarios:", c.get("/api/usuarios").json())

"""API de notas crédito: listado, filtro, PDF real, y bloqueo por permiso."""
import sys
sys.path.insert(0, "backend")
import httpx
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Usuario

BASE = "http://127.0.0.1:8000"

def login(email, clave):
    c = httpx.Client(base_url=BASE, timeout=30)
    r = c.post("/api/auth/login", data={"username": email, "password": clave})
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c

c = login("oscar.orozco03@gmail.com", "Admin1234*")

r = c.get("/api/notas-credito")
assert r.status_code == 200, r.text
data = r.json()
assert data["total"] >= 2 and len(data["items"]) >= 2
nota = data["items"][0]
print(f"1) listado: {data['total']} notas crédito, primera: {nota['numero']} de {nota['proveedor']['razon_social'][:30]}: OK")

r = c.get("/api/notas-credito?proveedor=OCUPAR")
assert r.status_code == 200 and r.json()["total"] >= 2
print(f"2) filtro por proveedor (OCUPAR): {r.json()['total']} resultados: OK")
r = c.get("/api/notas-credito?proveedor=NOEXISTEXYZ")
assert r.json()["total"] == 0
print("3) filtro sin coincidencias -> 0: OK")

r = c.get(f"/api/notas-credito/{nota['id']}/pdf")
assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
assert r.content[:4] == b"%PDF"
print(f"4) PDF real descargado ({len(r.content)} bytes, %PDF): OK")

# permiso: usuario 'area' (sin ver_todas_areas) no puede entrar
db = SessionLocal()
u = db.execute(select(Usuario).where(Usuario.email == "prueba.firmas@kos.com")).scalar_one_or_none()
if u:
    u.activo = True
    db.commit()
    b = login("prueba.firmas@kos.com", "Prueba1234*")
    r = b.get("/api/notas-credito")
    assert r.status_code == 403, f"esperaba 403, vino {r.status_code}"
    r = b.get(f"/api/notas-credito/{nota['id']}/pdf")
    assert r.status_code == 403
    print("5) rol 'area' (sin ver_todas_areas) bloqueado con 403 en listado y PDF: OK")
    u2 = db.get(Usuario, u.id)
    u2.activo = False
    db.commit()
    print("6) usuario de prueba desactivado de nuevo: OK")
else:
    print("5) (sin usuario de prueba para verificar permiso — omitido)")
db.close()

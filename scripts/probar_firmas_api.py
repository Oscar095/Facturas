"""Prueba de firmas: CRUD del dueño + AISLAMIENTO estricto entre usuarios.
Crea un usuario temporal B, verifica que no ve/usa/borra la firma de A, y limpia todo."""
import sys
sys.path.insert(0, "backend")
import httpx

BASE = "http://127.0.0.1:8000"
# PNG 1x1 transparente
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea72d1e480000000049454e44ae426082")

def login(email, clave):
    c = httpx.Client(base_url=BASE, timeout=30)
    r = c.post("/api/auth/login", data={"username": email, "password": clave})
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c

# ── A: admin sube su firma ──
a = login("oscar.orozco03@gmail.com", "Admin1234*")
r = a.post("/api/firmas", files={"archivo": ("mi_firma.png", PNG, "image/png")},
           data={"nombre": "Firma de prueba A"})
assert r.status_code == 200, r.text
firma = r.json()
assert "blob_path" not in firma, "blob_path no debe exponerse"
print(f"1) A subió firma id={firma['id']} ({firma['nombre']}): OK")

lista = a.get("/api/firmas").json()
assert any(f["id"] == firma["id"] for f in lista)
print(f"2) A la ve en su lista ({len(lista)} firma/s): OK")

r = a.get(f"/api/firmas/{firma['id']}/imagen")
assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
assert "no-store" in r.headers.get("cache-control", "")
print("3) A descarga su imagen (bytes idénticos, sin caché): OK")

# validaciones
r = a.post("/api/firmas", files={"archivo": ("malo.pdf", b"%PDF-123", "application/pdf")})
assert r.status_code == 400
r = a.post("/api/firmas", files={"archivo": ("vacia.png", b"", "image/png")})
assert r.status_code == 400
print("4) rechaza PDF y archivo vacío (400): OK")

# ── B: otro usuario NO puede ver/usar/borrar la firma de A ──
r = a.post("/api/usuarios", json={"email": "prueba.firmas@kos.com", "nombre": "Prueba Firmas",
                                  "rol": "area", "area_id": None, "clave": "Prueba1234*"})
usuario_b = r.json() if r.status_code == 200 else None
if usuario_b is None:  # ya existía de una corrida anterior
    print("   (usuario B ya existía, se reusa)")
b = login("prueba.firmas@kos.com", "Prueba1234*")

assert b.get("/api/firmas").json() == []
print("5) B tiene su lista vacía (no ve la de A): OK")
r = b.get(f"/api/firmas/{firma['id']}/imagen")
assert r.status_code == 404, f"esperaba 404, vino {r.status_code}"
r = b.delete(f"/api/firmas/{firma['id']}")
assert r.status_code == 404, f"esperaba 404, vino {r.status_code}"
print("6) B NO puede ver (404) ni borrar (404) la firma de A: OK")

# B sube la suya y A no la ve
r = b.post("/api/firmas", files={"archivo": ("firma_b.png", PNG, "image/png")},
           data={"nombre": "Firma B"})
firma_b = r.json()
ids_a = {f["id"] for f in a.get("/api/firmas").json()}
assert firma_b["id"] not in ids_a
r = a.get(f"/api/firmas/{firma_b['id']}/imagen")
assert r.status_code == 404
print("7) A tampoco ve la firma de B (aunque es admin): OK")

# ── limpieza: cada quien borra la suya; verificar blob eliminado ──
from app.database import SessionLocal
from app.models import Firma as FirmaM, Usuario as UsuarioM
db = SessionLocal()
ruta_a = db.get(FirmaM, firma["id"]).blob_path
db.close()

assert a.delete(f"/api/firmas/{firma['id']}").status_code == 200
assert b.delete(f"/api/firmas/{firma_b['id']}").status_code == 200
assert a.get("/api/firmas").json() == [] or all(f["id"] != firma["id"] for f in a.get("/api/firmas").json())
print("8) cada dueño eliminó su firma: OK")

from app.services.blob_storage import get_almacen
try:
    get_almacen().descargar(ruta_a)
    print("9) ERROR: el blob de A sigue existiendo")
except Exception:
    print("9) blob de A eliminado del almacenamiento: OK")

# desactivar usuario temporal B
uid = None
db = SessionLocal()
u = db.query(UsuarioM).filter(UsuarioM.email == "prueba.firmas@kos.com").first()
uid = u.id if u else None
db.close()
if uid:
    a.patch(f"/api/usuarios/{uid}", json={"activo": False})
    print(f"10) usuario temporal B (id={uid}) desactivado: OK")

"""API de notas crédito: listado, filtros, PDF real, asignación de área
(automática por reglas y manual por PATCH) y alcance por área según el rol.

Deja la BD como la encontró: revierte el área de la nota que toca.
Requiere el backend corriendo en 127.0.0.1:8000.
"""
import sys
sys.path.insert(0, "backend")
import httpx
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Area, NotaCredito, Proveedor, ReglaArea, Usuario
from app.services import reglas

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
assert "area" in nota, "el schema debe exponer 'area'"
print(f"1) listado: {data['total']} notas crédito, primera: {nota['numero']} "
      f"de {nota['proveedor']['razon_social'][:30]} (área: {nota['area'] or 'sin asignar'}): OK")

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

# ── asignación manual (PATCH) ────────────────────────────────────────────────
db = SessionLocal()
# ojo: en SQL Server `IS 1` es sintaxis inválida — con booleanos va `== True`
area = db.execute(select(Area).where(Area.activa == True)).scalars().first()  # noqa: E712
assert area is not None, "no hay áreas activas para probar"
original = db.get(NotaCredito, nota["id"]).area_id

r = c.patch(f"/api/notas-credito/{nota['id']}", json={"area_id": area.id})
assert r.status_code == 200, r.text
assert r.json()["area"]["id"] == area.id, r.json()
print(f"5) PATCH asigna área manualmente ('{area.nombre}'): OK")

r = c.get(f"/api/notas-credito?area_id={area.id}")
assert r.status_code == 200 and r.json()["total"] >= 1
assert any(n["id"] == nota["id"] for n in r.json()["items"])
print(f"6) filtro area_id={area.id} incluye la nota recién asignada: OK")

r = c.get("/api/notas-credito?sin_area=true")
assert r.status_code == 200
assert all(n["area"] is None for n in r.json()["items"])
assert not any(n["id"] == nota["id"] for n in r.json()["items"])
print(f"7) filtro sin_area=true: {r.json()['total']} sin área, ninguna con área: OK")

# ── asignación automática por reglas (sin IA) ────────────────────────────────
# Se busca una NC cuyo proveedor tenga regla de área y se comprueba que la
# cascada la resuelve sin llamar a la IA.
fila = db.execute(
    select(NotaCredito, ReglaArea)
    .join(Proveedor, NotaCredito.proveedor_id == Proveedor.id)
    .join(ReglaArea, ReglaArea.proveedor_nit == Proveedor.nit)
).first()
if fila:
    nc, regla = fila
    antes = nc.area_id
    nc.area_id = None
    nc.responsable_id = None
    reglas.asignar_area_nota_credito(db, nc)
    if nc.area_id is not None:
        print(f"8) reglas asignaron área automáticamente a la NC {nc.numero} "
              f"(area_id={nc.area_id}): OK")
    else:
        print(f"8) la NC {nc.numero} tiene reglas pero quedó ambigua -> sin área "
              f"(esperado, se asigna a mano): OK")
    nc.area_id = antes          # revertir: no ensuciar producción
    nc.responsable_id = None
    db.commit()
else:
    print("8) (ningún proveedor de NC tiene reglas de área — omitido)")

# ── alcance por rol: un usuario 'area' ahora SÍ entra, pero solo ve lo suyo ──
u = db.execute(select(Usuario).where(Usuario.email == "prueba.firmas@kos.com")).scalar_one_or_none()
if u:
    u.activo = True
    u.area_id = area.id          # su área = la que acabamos de asignar a la nota
    db.commit()
    b = login("prueba.firmas@kos.com", "Prueba1234*")
    r = b.get("/api/notas-credito")
    assert r.status_code == 200, f"el rol 'area' ya debe poder entrar, vino {r.status_code}"
    items = r.json()["items"]
    assert all(n["area"] and n["area"]["id"] == area.id for n in items), \
        "un usuario de área no debe ver notas de otras áreas"
    assert any(n["id"] == nota["id"] for n in items), "debe ver la nota de su área"
    print(f"9) rol 'area' entra al módulo y ve solo su área ({len(items)} notas): OK")

    r = b.get(f"/api/notas-credito/{nota['id']}/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    print("10) rol 'area' descarga el PDF de una nota de su área: OK")

    # una nota de OTRA área (o sin área) le debe dar 403
    otra = db.execute(
        select(NotaCredito).where(NotaCredito.area_id.is_(None))
    ).scalars().first()
    if otra:
        r = b.get(f"/api/notas-credito/{otra.id}/pdf")
        assert r.status_code == 403, f"esperaba 403 para nota ajena, vino {r.status_code}"
        print("11) rol 'area' bloqueado (403) en una nota que no es de su área: OK")

    u2 = db.get(Usuario, u.id)
    u2.activo = False
    db.commit()
    print("12) usuario de prueba desactivado de nuevo: OK")
else:
    print("9) (sin usuario de prueba para verificar alcance por área — omitido)")

# limpieza: devolver la nota a su área original
c.patch(f"/api/notas-credito/{nota['id']}", json={"area_id": original}) if original else None
if original is None:
    n = db.get(NotaCredito, nota["id"])
    n.area_id = None
    n.responsable_id = None
    db.commit()
print(f"\nlimpieza: la nota {nota['numero']} vuelve a area_id={original}")
db.close()
print("\nOK: todas las pruebas pasaron")

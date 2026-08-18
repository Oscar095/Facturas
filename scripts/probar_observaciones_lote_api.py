"""Prueba de los dos cambios de backend sobre facturas SINTÉTICAS:

  A) Historial de observaciones (tabla observaciones, append-only): cada nota
     queda con su autor y su fecha, se acumulan en orden y viajan tanto en el
     detalle como en el listado.
  B) POST /api/facturas/aprobar-lote — aprobar y firmar varias de una vez:
     SOLO facturas ya procesadas; omite (sin abortar) las demás detallando el
     motivo de cada una.

Crea su propia firma de prueba y limpia facturas, blobs, eventos y firma al final.
Funciona igual contra local y contra el App Service (la BD y el Blob son los
mismos), pasando la URL como argumento.

Uso: .venv/Scripts/python.exe scripts/probar_observaciones_lote_api.py [URL]
     ... scripts/probar_observaciones_lote_api.py https://facturacion.azurewebsites.net
"""
import sys

sys.path.insert(0, "backend")
from io import BytesIO  # noqa: E402

import httpx  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Area, Documento, Evento, Factura, Observacion, Proveedor, ahora,
)
from app.services.blob_storage import get_almacen  # noqa: E402

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
almacen = get_almacen()

img = Image.new("RGBA", (400, 140), (0, 0, 0, 0))
ImageDraw.Draw(img).line([(20, 100), (80, 40), (140, 110), (340, 60)],
                         fill=(25, 35, 95, 255), width=6)
_buf = BytesIO(); img.save(_buf, "PNG"); PNG_FIRMA = _buf.getvalue()


def pdf_prueba(paginas=1):
    b = BytesIO()
    c = rl_canvas.Canvas(b, pagesize=(612, 792))
    for i in range(paginas):
        c.drawString(72, 720, f"FACTURA DE PRUEBA - pagina {i + 1}")
        c.showPage()
    c.save()
    return b.getvalue()


# ── 4 facturas sintéticas que cubren los cuatro caminos del lote ──
db = SessionLocal()
prov = db.execute(select(Proveedor)).scalars().first()
area = db.execute(select(Area)).scalars().first()

CASOS = [
    ("LOTE-1", "procesada", True),            # se firma
    ("LOTE-2", "procesada", True),            # se firma
    ("LOTE-3", "procesada", False),           # sin área -> omitida
    ("LOTE-4", "aprobada", True),             # ya aprobada -> omitida
    ("LOTE-5", "lista_contabilizar", True),   # aún no procesada -> omitida
]
ids: dict[str, int] = {}
for numero, estado, con_area in CASOS:
    ruta = f"prueba_lote/{numero}.pdf"
    almacen.subir(ruta, pdf_prueba(2), content_type="application/pdf")
    f = Factura(cufe=f"TEST-{numero}", prefijo="", numero=numero, proveedor_id=prov.id,
                fecha_recepcion=ahora(), estado_proceso=estado,
                area_id=area.id if con_area else None, blob_pdf=ruta)
    db.add(f); db.flush()
    db.add(Documento(factura_id=f.id, tipo="FV", blob_path=ruta,
                     nombre_archivo=f"{numero}.pdf"))
    ids[numero] = f.id
db.commit()
db.close()
print(f"facturas sintéticas: {ids}")

print(f"probando contra {BASE}")
c = httpx.Client(base_url=BASE, timeout=180, follow_redirects=True)
r = c.post("/api/auth/login",
           data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

firma_id = None
try:
    # ═══ A) historial de observaciones ═══
    fid = ids["LOTE-1"]
    NOTA1 = "El CRN llega la próxima semana; el proveedor ya despachó."
    NOTA2 = "Confirmado con compras: la OCS cubre el servicio completo."

    r = c.post(f"/api/facturas/{fid}/observaciones", json={"texto": NOTA1})
    assert r.status_code == 200, r.text
    assert [o["texto"] for o in r.json()["observaciones"]] == [NOTA1], r.json()
    print("A1) POST agrega la primera nota y la devuelve en el detalle: OK")

    r = c.post(f"/api/facturas/{fid}/observaciones", json={"texto": NOTA2})
    assert [o["texto"] for o in r.json()["observaciones"]] == [NOTA1, NOTA2], r.json()
    print("A2) la segunda nota se ACUMULA (no reemplaza) y queda en orden: OK")

    r = c.get(f"/api/facturas/{fid}")
    obs = r.json()["observaciones"]
    assert len(obs) == 2 and obs[0]["usuario"]["nombre"], obs
    assert obs[0]["fecha"] and obs[0]["id"] != obs[1]["id"]
    print("A3) cada nota trae autor y fecha: OK")

    # el listado también las trae: el jefe las ve al aprobar en bloque sin entrar
    r = c.get("/api/facturas?proveedor=" + prov.nit)
    fila = next(x for x in r.json()["items"] if x["id"] == fid)
    assert [o["texto"] for o in fila["observaciones"]] == [NOTA1, NOTA2], fila
    print("A4) el listado incluye el historial (indicador para el aprobador): OK")

    db2 = SessionLocal()
    evs = db2.execute(select(Evento).where(Evento.factura_id == fid,
                                           Evento.accion == "observacion")).scalars().all()
    assert len(evs) == 2, evs
    db2.close()
    print("A5) cada nota queda auditada en eventos: OK")

    r = c.post(f"/api/facturas/{fid}/observaciones", json={"texto": "   "})
    assert r.status_code == 422, r.status_code
    print("A6) nota vacía o en blanco se rechaza (422): OK")

    r = c.post(f"/api/facturas/{fid}/observaciones", json={"texto": "x" * 2001})
    assert r.status_code == 422, r.status_code
    print("A7) más de 2000 caracteres se rechaza (422): OK")

    # ═══ B) aprobación por lote ═══
    r = c.post("/api/firmas", files={"archivo": ("firma_lote.png", PNG_FIRMA, "image/png")},
               data={"nombre": "Firma prueba lote"})
    firma_id = r.json()["id"]

    todas = [ids[n] for n, _, _ in CASOS]

    r = c.post("/api/facturas/aprobar-lote", json={"ids": todas, "firma_id": 999999})
    assert r.status_code == 404, r.text
    print("B1) firma ajena/inexistente rechazada (404): OK")

    r = c.post("/api/facturas/aprobar-lote", json={"ids": [], "firma_id": firma_id})
    assert r.status_code == 400, r.text
    print("B2) lote vacío rechazado (400): OK")

    # ids duplicados: la factura no debe firmarse dos veces
    r = c.post("/api/facturas/aprobar-lote",
               json={"ids": todas + [ids["LOTE-1"]], "firma_id": firma_id})
    assert r.status_code == 200, r.text
    res = r.json()
    por_id = {x["factura_id"]: x for x in res["resultados"]}
    assert res["aprobadas"] == 2 and res["omitidas"] == 3 and res["errores"] == 0, res
    assert len(res["resultados"]) == 5, "los ids duplicados no se deduplicaron"
    print("B3) 2 aprobadas / 3 omitidas / 0 errores (ids duplicados ignorados): OK")

    assert por_id[ids["LOTE-1"]]["estado"] == "aprobada"
    assert por_id[ids["LOTE-2"]]["estado"] == "aprobada"
    assert por_id[ids["LOTE-3"]]["estado"] == "omitida"
    assert "área" in por_id[ids["LOTE-3"]]["detalle"], por_id[ids["LOTE-3"]]
    assert por_id[ids["LOTE-4"]]["estado"] == "omitida"
    assert "aprobada" in por_id[ids["LOTE-4"]]["detalle"], por_id[ids["LOTE-4"]]
    assert por_id[ids["LOTE-5"]]["estado"] == "omitida"
    assert "procesada" in por_id[ids["LOTE-5"]]["detalle"], por_id[ids["LOTE-5"]]
    print("B4) motivos por factura (sin área / ya aprobada / aún no procesada): OK")

    db3 = SessionLocal()
    f1 = db3.get(Factura, ids["LOTE-1"])
    f3 = db3.get(Factura, ids["LOTE-3"])
    f5 = db3.get(Factura, ids["LOTE-5"])
    assert f1.estado_proceso == "aprobada" and f3.estado_proceso == "procesada"
    assert f5.estado_proceso == "lista_contabilizar", (
        "el lote NO debe procesar por su cuenta lo que no estaba procesado")
    assert f1.blob_pdf == "prueba_lote/LOTE-1_firmado.pdf", f1.blob_pdf
    doc1 = db3.execute(select(Documento).where(
        Documento.factura_id == ids["LOTE-1"])).scalars().first()
    assert doc1.blob_path == "prueba_lote/LOTE-1_firmado.pdf", doc1.blob_path
    print("B5) estados y rutas al PDF firmado actualizados; la omitida quedó intacta: OK")

    lector = PdfReader(BytesIO(almacen.descargar("prueba_lote/LOTE-1_firmado.pdf")))
    assert len(lector.pages) == 2
    for i, pagina in enumerate(lector.pages):
        assert "Aprobado por" in (pagina.extract_text() or ""), f"sin sello en página {i + 1}"
        assert "/XObject" in pagina.get("/Resources", {}), f"sin imagen en página {i + 1}"
    print("B6) sello (texto + imagen de firma) en TODAS las páginas: OK")

    acciones = [e.accion for e in db3.execute(select(Evento).where(
        Evento.factura_id == ids["LOTE-1"])).scalars()]
    assert "aprobada" in acciones and "procesada" not in acciones, acciones
    ev_ap = db3.execute(select(Evento).where(
        Evento.factura_id == ids["LOTE-1"], Evento.accion == "aprobada")).scalars().first()
    assert "lote" in ev_ap.detalle, ev_ap.detalle
    db3.close()
    print("B7) auditoría: 'aprobada … por lote', sin procesar nada por su cuenta: OK")

    # reintentar el mismo lote no hace nada (todas ya aprobadas u omitidas)
    r = c.post("/api/facturas/aprobar-lote", json={"ids": todas, "firma_id": firma_id})
    assert r.json()["aprobadas"] == 0 and r.json()["omitidas"] == 5, r.json()
    print("B8) reintentar el lote es inocuo (no vuelve a firmar): OK")

finally:
    db4 = SessionLocal()
    for fid_ in ids.values():
        db4.query(Evento).filter(Evento.factura_id == fid_).delete()
        db4.query(Observacion).filter(Observacion.factura_id == fid_).delete()
        for d in db4.query(Documento).filter(Documento.factura_id == fid_).all():
            db4.delete(d)
        obj = db4.get(Factura, fid_)
        if obj:
            db4.delete(obj)
    db4.commit(); db4.close()
    for numero, _, _ in CASOS:
        for ruta in (f"prueba_lote/{numero}.pdf", f"prueba_lote/{numero}_firmado.pdf"):
            try:
                almacen.eliminar(ruta)
            except Exception:  # noqa: BLE001 — el firmado no existe si se omitió
                pass
    if firma_id:
        c.delete(f"/api/firmas/{firma_id}")
    print("limpieza (facturas, documentos, eventos, blobs y firma de prueba): OK")

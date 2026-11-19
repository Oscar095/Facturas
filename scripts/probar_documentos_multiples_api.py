"""Regresión del bug de los adjuntos que se pisaban, y de "cualquier tipo de archivo".

El bug: la ruta en el Blob era `documentos/{factura}/{tipo}_{numero}.{ext}`, así que
varios archivos del mismo tipo caían en la misma ruta, cada subida sobrescribía a la
anterior y todas las filas abrían el ÚLTIMO archivo. Se perdieron 40 documentos reales.

Sobre una factura SINTÉTICA comprueba que:
  1. varios archivos del mismo tipo (y hasta con el MISMO nombre) quedan en rutas
     distintas y cada uno descarga exactamente SUS bytes;
  2. se acepta cualquier tipo de archivo (PDF, JPEG, Excel, .msg, sin extensión);
  3. un nombre con caracteres fuera de latin-1 (guion largo) se descarga sin 500;
  4. al aprobar, la firma se estampa SOLO en los PDF — cada uno sobre su propio
     contenido — y los demás quedan omitidos y anotados en el evento.
Limpia factura, eventos, blobs y la firma de prueba al terminar.

Requiere el backend corriendo en 127.0.0.1:8000.
Uso: .venv/Scripts/python.exe scripts/probar_documentos_multiples_api.py
"""
import sys
from io import BytesIO

sys.path.insert(0, "backend")

import httpx  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Area, Documento, Evento, Factura, Proveedor, ahora  # noqa: E402
from app.services.blob_storage import get_almacen  # noqa: E402

BASE = "http://127.0.0.1:8000"
almacen = get_almacen()


def pdf_con(texto: str) -> bytes:
    b = BytesIO()
    c = rl_canvas.Canvas(b, pagesize=(612, 792))
    c.drawString(72, 720, texto)
    c.showPage()
    c.save()
    return b.getvalue()


img = Image.new("RGBA", (400, 140), (0, 0, 0, 0))
ImageDraw.Draw(img).line([(20, 100), (120, 40), (220, 110), (340, 60)],
                         fill=(25, 35, 95, 255), width=6)
buf = BytesIO(); img.save(buf, "PNG"); PNG_FIRMA = buf.getvalue()

# (nombre, bytes, content-type) — todos se suben como OTRO, en un solo "paso"
ARCHIVOS = [
    ("soporte 1.pdf", pdf_con("SOPORTE UNO 111"), "application/pdf"),
    ("soporte 2.pdf", pdf_con("SOPORTE DOS 222"), "application/pdf"),
    ("foto.jpeg", b"\xff\xd8\xff\xe0 foto de prueba", "image/jpeg"),
    ("Cotización – final.xlsx", b"PK\x03\x04 excel de prueba", "application/octet-stream"),
    ("correo.msg", b"\xd0\xcf\x11\xe0 correo de prueba", "application/vnd.ms-outlook"),
    ("sin_extension", b"archivo sin extension", "application/octet-stream"),
    # MISMO nombre que el primero pero otro contenido: tampoco puede pisarlo
    ("soporte 1.pdf", pdf_con("SOPORTE UNO BIS 333"), "application/pdf"),
]

db = SessionLocal()
prov = db.execute(select(Proveedor)).scalars().first()
area = db.execute(select(Area)).scalars().first()
almacen.subir("prueba_multi/fv.pdf", pdf_con("FACTURA DE PRUEBA"), content_type="application/pdf")
f = Factura(cufe="TEST-MULTI-DOCS", prefijo="", numero="TEST-MULTI-1", proveedor_id=prov.id,
            fecha_recepcion=ahora(), estado_proceso="asignada", area_id=area.id,
            blob_pdf="prueba_multi/fv.pdf")
db.add(f); db.flush()
fid = f.id
db.add(Documento(factura_id=fid, tipo="FV", blob_path="prueba_multi/fv.pdf", nombre_archivo="fv.pdf"))
db.commit(); db.close()
print(f"factura sintética id={fid}")

c = httpx.Client(base_url=BASE, timeout=120)
r = c.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

firma_id = None
rutas_creadas: set[str] = set()
try:
    # ── 1) y 2) varios archivos del mismo tipo, de cualquier clase ──
    for nombre, datos, ct in ARCHIVOS:
        r = c.post(f"/api/documentos/{fid}", data={"tipo": "OTRO"},
                   files={"archivo": (nombre, datos, ct)})
        assert r.status_code == 200, (nombre, r.status_code, r.text)

    db2 = SessionLocal()
    adjuntos = db2.execute(select(Documento).where(Documento.factura_id == fid,
                                                   Documento.tipo == "OTRO")
                           .order_by(Documento.id)).scalars().all()
    db2.close()
    rutas_creadas |= {d.blob_path for d in adjuntos}
    assert len(adjuntos) == len(ARCHIVOS), f"se esperaban {len(ARCHIVOS)} filas, hay {len(adjuntos)}"
    assert len({d.blob_path for d in adjuntos}) == len(ARCHIVOS), \
        "hay documentos compartiendo ruta en el Blob — el bug volvió"
    print(f"1) {len(ARCHIVOS)} archivos tipo OTRO (dos con el mismo nombre) -> "
          f"{len(ARCHIVOS)} rutas distintas: OK")

    for doc, (nombre, datos, _) in zip(adjuntos, ARCHIVOS):
        r = c.get(f"/api/facturas/documento/{doc.id}/archivo")
        assert r.status_code == 200, (nombre, r.status_code, r.text[:200])
        assert r.content == datos, f"{nombre} descarga bytes que no son suyos"
        assert doc.nombre_archivo == nombre, (doc.nombre_archivo, nombre)
    print("2) cada documento descarga EXACTAMENTE sus bytes, incluidos Excel, .msg, "
          "JPEG y un archivo sin extensión: OK")

    cot = next(d for d in adjuntos if d.nombre_archivo.startswith("Cotiz"))
    r = c.get(f"/api/facturas/documento/{cot.id}/archivo")
    assert "filename*=UTF-8''Cotizaci%C3%B3n%20%E2%80%93%20final.xlsx" in r.headers["content-disposition"]
    print("3) nombre con tilde y guion largo se descarga (200) con su nombre real: OK")

    # ── 4) aprobar: firma solo en los PDF, cada uno sobre su propio contenido ──
    r = c.post(f"/api/facturas/{fid}/procesar")
    assert r.status_code == 200, r.text
    r = c.post("/api/firmas", files={"archivo": ("firma_test.png", PNG_FIRMA, "image/png")},
               data={"nombre": "Firma prueba adjuntos"})
    firma_id = r.json()["id"]
    r = c.post(f"/api/facturas/{fid}/aprobar", json={"firma_id": firma_id})
    assert r.status_code == 200, r.text

    db3 = SessionLocal()
    docs = {d.id: d for d in db3.execute(select(Documento).where(Documento.factura_id == fid)).scalars()}
    evento = db3.execute(select(Evento).where(Evento.factura_id == fid,
                                              Evento.accion == "aprobada")).scalars().first()
    fv_path = db3.get(Factura, fid).blob_pdf
    db3.close()
    rutas_creadas |= {d.blob_path for d in docs.values()} | {fv_path}

    textos_esperados = {"soporte 1.pdf": ["SOPORTE UNO 111", "SOPORTE UNO BIS 333"],
                        "soporte 2.pdf": ["SOPORTE DOS 222"]}
    vistos = []
    for doc in adjuntos:
        actual = docs[doc.id]
        if doc.nombre_archivo.lower().endswith(".pdf"):
            assert actual.blob_path.endswith("_firmado.pdf"), actual.blob_path
            texto = PdfReader(BytesIO(almacen.descargar(actual.blob_path))).pages[0].extract_text()
            assert "Aprobado por" in texto, f"{doc.nombre_archivo} sin sello"
            propio = next(t for t in textos_esperados[doc.nombre_archivo] if t in texto)
            vistos.append(propio)
        else:
            assert actual.blob_path == doc.blob_path, f"{doc.nombre_archivo} no es PDF y cambió de ruta"
    assert sorted(vistos) == ["SOPORTE DOS 222", "SOPORTE UNO 111", "SOPORTE UNO BIS 333"], vistos
    print("4) los 3 PDF quedaron firmados, cada uno sobre SU contenido (no el último subido): OK")

    assert evento.detalle.count("(no es PDF)") == 4, evento.detalle
    print("5) los 4 no-PDF quedaron adjuntos sin firma y anotados en el evento: OK")
finally:
    db4 = SessionLocal()
    for d in db4.execute(select(Documento).where(Documento.factura_id == fid)).scalars().all():
        rutas_creadas.add(d.blob_path)
        db4.delete(d)
    db4.query(Evento).filter(Evento.factura_id == fid).delete()
    fx = db4.get(Factura, fid)
    if fx:
        db4.delete(fx)
    db4.commit(); db4.close()
    rutas_creadas |= {"prueba_multi/fv.pdf", "prueba_multi/fv_firmado.pdf"}
    for ruta in rutas_creadas:
        almacen.eliminar(ruta)
        if ruta.endswith("_firmado.pdf"):
            almacen.eliminar(ruta.replace("_firmado", ""))
    if firma_id:
        c.delete(f"/api/firmas/{firma_id}")
    print("limpieza (factura, documentos, blobs y firma de prueba): OK")

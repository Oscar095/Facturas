"""UI: subir varios archivos de una vez, de cualquier tipo, y abrir un no-PDF.

Sobre una factura SINTÉTICA: elige 3 archivos a la vez en "Cargar documento"
(dos PDF y un Excel, todos tipo "Otro"), comprueba que aparecen 3 filas y que cada
una descarga su propio archivo, y que el Excel se DESCARGA con su nombre real en
vez de abrirse como blob sin extensión. Limpia todo al terminar.

Requiere el backend corriendo en 127.0.0.1:8000 sirviendo frontend/dist.
Uso: .venv/Scripts/python.exe scripts/probar_ui_documentos_multiples.py
"""
import sys
import tempfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, "backend")

from playwright.sync_api import sync_playwright  # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Area, Documento, Evento, Factura, Proveedor, ahora  # noqa: E402
from app.services.blob_storage import get_almacen  # noqa: E402

BASE = "http://127.0.0.1:8000"
EMAIL, CLAVE = "oscar.orozco03@gmail.com", "Admin1234*"
almacen = get_almacen()


def pdf_con(texto: str) -> bytes:
    b = BytesIO()
    c = rl_canvas.Canvas(b)
    c.drawString(72, 720, texto)
    c.showPage()
    c.save()
    return b.getvalue()


tmp = Path(tempfile.mkdtemp(prefix="multi_ui_"))
ARCHIVOS = {
    "soporte A.pdf": pdf_con("SOPORTE A"),
    "soporte B.pdf": pdf_con("SOPORTE B"),
    "Cotización – proveedor.xlsx": b"PK\x03\x04 excel de prueba UI",
}
for nombre, datos in ARCHIVOS.items():
    (tmp / nombre).write_bytes(datos)

db = SessionLocal()
prov = db.execute(select(Proveedor)).scalars().first()
area = db.execute(select(Area)).scalars().first()
almacen.subir("prueba_multi_ui/fv.pdf", pdf_con("FV UI"), content_type="application/pdf")
f = Factura(cufe="TEST-MULTI-UI", prefijo="", numero="TEST-MULTI-UI", proveedor_id=prov.id,
            fecha_recepcion=ahora(), estado_proceso="asignada", area_id=area.id,
            blob_pdf="prueba_multi_ui/fv.pdf")
db.add(f); db.flush()
fid = f.id
db.add(Documento(factura_id=fid, tipo="FV", blob_path="prueba_multi_ui/fv.pdf", nombre_archivo="fv.pdf"))
db.commit(); db.close()
print(f"factura sintética id={fid}")

errores: list[str] = []
fallos = 0
try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(accept_downloads=True)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errores.append(str(e)))

        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.fill("input[type=email]", EMAIL)
        page.fill("input[type=password]", CLAVE)
        page.click("button:has-text('Ingresar')")
        page.wait_for_selector(".sidebar", timeout=20000)
        page.goto(f"{BASE}/facturas/{fid}", wait_until="networkidle")
        page.wait_for_selector("form.cargar input[type=file]", timeout=15000)

        page.select_option("form.cargar select", "OTRO")
        page.set_input_files("form.cargar input[type=file]",
                             [str(tmp / n) for n in ARCHIVOS])
        page.click("form.cargar button")
        # la subida es secuencial: esperar a que el botón vuelva a "Subir"
        page.wait_for_function(
            "() => document.querySelector('form.cargar button').textContent.trim() === 'Subir'",
            timeout=60000,
        )
        filas = page.locator(".detalle table.tabla tbody tr", has_text="OTRO")
        if filas.count() != 3:
            fallos += 1
            print(f"   FALLO: se esperaban 3 filas OTRO, hay {filas.count()}")
        else:
            print("1) 3 archivos elegidos a la vez -> 3 documentos en la tabla: OK")

        db2 = SessionLocal()
        docs = db2.execute(select(Documento).where(Documento.factura_id == fid,
                                                   Documento.tipo == "OTRO")).scalars().all()
        db2.close()
        rutas = {d.blob_path for d in docs}
        contenidos = {d.nombre_archivo: almacen.descargar(d.blob_path) for d in docs}
        if len(rutas) != 3 or any(contenidos.get(n) != datos for n, datos in ARCHIVOS.items()):
            fallos += 1
            print("   FALLO: los documentos comparten ruta o no guardan su propio contenido")
        else:
            print("2) cada documento guardó su propio archivo en su propia ruta: OK")

        # el Excel no se abre en pestaña: se descarga con su nombre real
        excel = next(n for n in ARCHIVOS if n.endswith(".xlsx"))
        with page.expect_download(timeout=15000) as descarga:
            page.locator(".detalle table.tabla a", has_text="Cotiz").click()
        d = descarga.value
        if d.suggested_filename != excel or Path(d.path()).read_bytes() != ARCHIVOS[excel]:
            fallos += 1
            print(f"   FALLO: la descarga llegó como {d.suggested_filename!r}")
        else:
            print("3) el Excel se descarga con su nombre real (tilde y guion largo incluidos): OK")

        if page.locator(".detalle .error").count():
            fallos += 1
            print(f"   FALLO: error en pantalla: {page.locator('.detalle .error').first.inner_text()}")
        b.close()
finally:
    db3 = SessionLocal()
    for dd in db3.execute(select(Documento).where(Documento.factura_id == fid)).scalars().all():
        almacen.eliminar(dd.blob_path)
        db3.delete(dd)
    db3.query(Evento).filter(Evento.factura_id == fid).delete()
    fx = db3.get(Factura, fid)
    if fx:
        db3.delete(fx)
    db3.commit(); db3.close()
    almacen.eliminar("prueba_multi_ui/fv.pdf")
    print("limpieza (factura, documentos y blobs de prueba): OK")

print(f"\nerrores de página: {errores or 'ninguno'}")
print("OK: subida múltiple y descarga de no-PDF funcionan" if not fallos and not errores
      else f"{fallos} COMPROBACIONES FALLARON")
sys.exit(1 if fallos or errores else 0)

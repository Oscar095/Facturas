"""Spike (solo lectura): ¿el portal permite descargar el XML de la factura?

Paso 2 del plan vencimiento: el XML UBL de la DIAN trae la fecha de vencimiento
oficial (cbc:DueDate / PaymentDueDate). Busca una factura por CUFE (como hace la
descarga de PDF), abre el menú de la fila e imprime TODAS las opciones; si hay
una de XML, la descarga y busca DueDate en el contenido.

Uso: .venv/Scripts/python.exe scripts/explorar_xml_portal.py [dias]
"""
import re
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, "backend")

from app.config import settings  # noqa: E402
from app.ingesta.siesa_client import SiesaClient  # noqa: E402

dias = int(sys.argv[1]) if len(sys.argv) > 1 else 5
hasta = date.today()
desde = hasta - timedelta(days=dias)

with SiesaClient(settings.url_facturas, settings.username_facturas,
                 settings.password_facturas) as siesa:
    docs = siesa.listar_documentos(desde.isoformat(), hasta.isoformat(), tipo_doc="1")
    print(f"{len(docs)} facturas en el rango; uso la primera: {docs[0].folio}")
    doc = docs[0]

    p = siesa.page
    siesa._cerrar_modales()
    siesa._fijar_tipo_documento("1")
    if doc.fecha:
        siesa._fijar_rango_fecha(doc.fecha, doc.fecha)
    caja = p.locator("input[placeholder*='CUFE' i]").first
    caja.fill("")
    caja.fill(doc.cufe)
    p.locator("button:has-text('Buscar')").first.click()
    p.wait_for_load_state("networkidle", timeout=60000)
    time.sleep(2)
    assert p.locator("table tbody tr").count() > 0, "sin filas para el CUFE"

    fila = p.locator("table tbody tr").first
    fila.locator("button.btn-default-drop").click()
    time.sleep(0.5)
    opciones = [t.strip() for t in fila.locator("a").all_inner_texts() if t.strip()]
    print(f"\nOPCIONES del menú de la fila: {opciones}")

    xml_opcion = next((o for o in opciones if "xml" in o.lower()), None)
    if not xml_opcion:
        print("\nNo hay opción de XML en el menú. Habrá que ir por otra vía.")
        sys.exit(0)

    print(f"\nProbando la opción: {xml_opcion!r}")
    contenido = None
    try:
        with p.expect_download(timeout=20000) as dl_info:
            fila.locator(f"a:has-text('{xml_opcion}')").click()
        ruta = dl_info.value.path()
        contenido = open(ruta, "rb").read().decode("utf-8", errors="replace")
        print(f"-> llegó como DESCARGA ({dl_info.value.suggested_filename})")
    except Exception:
        print("-> no fue descarga; intento capturar la respuesta HTTP...")
        try:
            with p.expect_response(
                lambda r: "xml" in r.headers.get("content-type", "").lower()
                or "xml" in r.url.lower(),
                timeout=20000,
            ) as resp_info:
                fila.locator(f"a:has-text('{xml_opcion}')").click()
            contenido = resp_info.value.text()
            print(f"-> respuesta HTTP {resp_info.value.status} {resp_info.value.url[:100]}")
        except Exception as e:
            print(f"-> tampoco hubo respuesta XML detectable: {e}")

    if contenido:
        print(f"\nTamaño: {len(contenido)} chars. Primeros 500:\n{contenido[:500]}")
        m = re.search(r"<cbc:DueDate>([^<]+)</cbc:DueDate>", contenido)
        m2 = re.search(r"<cbc:PaymentDueDate>([^<]+)</cbc:PaymentDueDate>", contenido)
        print(f"\ncbc:DueDate = {m.group(1) if m else 'NO PRESENTE'}")
        print(f"cbc:PaymentDueDate = {m2.group(1) if m2 else 'NO PRESENTE'}")
        print(f"emisión del doc (para comparar): {doc.fecha}")

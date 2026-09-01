"""UI del dashboard: mes por EMISIÓN, notas crédito neteadas y celdas negativas.

Crea una factura y dos notas crédito sintéticas en 2025 (la BD real arranca en
2026-07, así que las cifras del mes se pueden leer exactas) y comprueba lo que
ve el usuario en pantalla, no solo lo que devuelve la API. Limpia al terminar.

Requiere el backend corriendo en 127.0.0.1:8000 sirviendo frontend/dist.
Uso: .venv/Scripts/python.exe scripts/probar_ui_dashboard.py
"""
import sys
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, "backend")

from playwright.sync_api import sync_playwright  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Area, Factura, NotaCredito, Proveedor  # noqa: E402

BASE = "http://127.0.0.1:8000"
EMAIL, CLAVE = "oscar.orozco03@gmail.com", "Admin1234*"
NIT = "900000000-8"
D = Decimal


def imprimible(texto: str) -> str:
    """La consola de Windows es cp1252 y revienta con el signo menos tipográfico
    (U+2212) que usa la tarjeta del panel."""
    return texto.encode("ascii", "replace").decode()

db = SessionLocal()
area = db.execute(select(Area)).scalars().first()
prov = db.execute(select(Proveedor).where(Proveedor.nit == NIT)).scalar_one_or_none()
if prov is None:
    prov = Proveedor(nit=NIT, razon_social="PROVEEDOR PRUEBA UI PANEL")
    db.add(prov); db.flush()
prov_id, area_id, area_nombre = prov.id, area.id, area.nombre

f1 = Factura(cufe="TESTUIPANEL-F1", numero="UIPANEL-F1", proveedor_id=prov_id,
             fecha_emision=datetime(2025, 3, 12), fecha_recepcion=datetime(2025, 4, 2),
             valor_total=D("11900000.00"), iva=D("1900000.00"),
             estado_proceso="nueva", area_id=area_id)
nc1 = NotaCredito(cufe="TESTUIPANEL-NC1", numero="UIPANEL-NC1", proveedor_id=prov_id,
                  fecha_emision=datetime(2025, 3, 20), fecha_recepcion=datetime(2025, 4, 2),
                  valor_total=D("2380000.00"), iva=D("380000.00"), area_id=area_id)
# abril: SOLO nota crédito -> celda negativa en el mapa de calor
nc2 = NotaCredito(cufe="TESTUIPANEL-NC2", numero="UIPANEL-NC2", proveedor_id=prov_id,
                  fecha_emision=datetime(2025, 4, 8), fecha_recepcion=datetime(2025, 4, 9),
                  valor_total=D("1190000.00"), iva=D("190000.00"), area_id=area_id)
for obj in (f1, nc1, nc2):
    db.add(obj)
db.commit()
ids_f, ids_nc = [f1.id], [nc1.id, nc2.id]
db.close()
print(f"sintéticas: factura {ids_f}, notas crédito {ids_nc} (área {area_nombre})")

errores: list[str] = []
fallos = 0
try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context().new_page()
        page.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errores.append(str(e)))

        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.fill("input[type=email]", EMAIL)
        page.fill("input[type=password]", CLAVE)
        page.click("button:has-text('Ingresar')")
        page.wait_for_selector(".kpis .kpi", timeout=20000)

        # el dashboard es la página de inicio; se elige marzo de 2025 en el selector
        page.select_option(".selector-mes select", "2025-03")
        page.wait_for_function(
            "() => document.querySelectorAll('.kpis .kpi')[0]"
            ".textContent.includes('marzo')",
            timeout=15000,
        )

        kpi_facturas = page.locator(".kpis .kpi").nth(0).inner_text()
        if "1" not in kpi_facturas or "emitidas en marzo" not in kpi_facturas.lower():
            fallos += 1
            print(f"   FALLO: la tarjeta de facturas no dice 'emitidas en marzo': {kpi_facturas!r}")
        else:
            print("1) la tarjeta del mes cuenta por EMISIÓN (la factura del 12-mar "
                  "recibida el 2-abr): OK")

        kpi_valor = page.locator(".kpis .kpi").nth(3).inner_text()
        # 10.000.000 facturado - 2.000.000 de nota crédito = 8.000.000
        if "8" not in kpi_valor or "nota" not in kpi_valor.lower():
            fallos += 1
            print(f"   FALLO: la tarjeta de valor no muestra el neto ni la nota crédito: {kpi_valor!r}")
        else:
            print(f"2) la tarjeta de valor muestra el neto y el descuento: "
                  f"{imprimible(kpi_valor.splitlines()[-1].strip())}: OK")

        # barra del área con la anotación de notas crédito
        barra = page.locator(".barra-fila", has_text=area_nombre).first
        if barra.locator(".barra-nc").count() != 1:
            fallos += 1
            print("   FALLO: la barra del área no anota las notas crédito descontadas")
        else:
            print("3) la barra del área anota lo descontado "
                  f"({imprimible(barra.locator('.barra-nc').inner_text().strip())}): OK")

        # abril tiene SOLO nota crédito: en la matriz debe salir una celda negativa
        page.select_option(".selector-mes select", "2025-04")
        # la cabecera corta de la matriz es 'abr 25' (etiquetaMes sin largo)
        page.wait_for_function(
            "() => document.querySelector('.tabla.matriz thead')"
            ".textContent.includes('abr 25')",
            timeout=15000,
        )
        negativas = page.locator(".tabla.matriz td.celda-neg")
        if negativas.count() < 1:
            fallos += 1
            print("   FALLO: el mes con solo notas crédito no se pinta como celda negativa")
        else:
            print("4) el mes con solo notas crédito se pinta aparte "
                  f"({imprimible(negativas.first.inner_text().strip())}), "
                  "fuera de la rampa azul: OK")

        page.screenshot(path="dashboard-neto.png", full_page=True)
        b.close()
finally:
    db2 = SessionLocal()
    for modelo, ids in ((Factura, ids_f), (NotaCredito, ids_nc)):
        for oid in ids:
            obj = db2.get(modelo, oid)
            if obj:
                db2.delete(obj)
    db2.flush()
    pr = db2.get(Proveedor, prov_id)
    if pr:
        db2.delete(pr)
    db2.commit(); db2.close()
    print("limpieza (factura, notas crédito y proveedor de prueba): OK")

print(f"\nerrores de consola: {errores or 'ninguno'}")
print("OK: el dashboard muestra el neto por fecha de emisión" if not fallos
      else f"{fallos} COMPROBACIONES FALLARON")
sys.exit(1 if fallos or errores else 0)

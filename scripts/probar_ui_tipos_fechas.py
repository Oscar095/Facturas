"""UI: página Notas Crédito (datos reales), badge/filtro Tipo y filtro de fechas
en Facturas. Todo con datos reales ya ingestados — no crea nada."""
from playwright.sync_api import sync_playwright, expect

errores = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_context().new_page()
    page.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errores.append(str(e)))

    page.goto("http://127.0.0.1:8000/login", wait_until="networkidle")
    page.fill("input[type=email]", "oscar.orozco03@gmail.com")
    page.fill("input[type=password]", "Admin1234*")
    page.click("button:has-text('Ingresar')")
    page.wait_for_selector(".sidebar", timeout=15000)

    # 1. link y página de Notas Crédito con datos reales
    link = page.locator(".sidenav a", has_text="Notas Crédito")
    expect(link).to_have_count(1)
    link.click()
    page.wait_for_selector("h1:has-text('Notas Crédito')", timeout=8000)
    expect(page.locator("table.tabla tbody tr", has_text="NV17435")).to_have_count(1, timeout=8000)
    filas = page.locator("table.tabla tbody tr").count()
    print(f"1) página Notas Crédito con {filas} filas reales (NV17435 visible): OK")

    # 2. Ver PDF de una nota crédito (sin errores en UI)
    with page.context.expect_page(timeout=10000):
        page.locator("table.tabla tbody tr", has_text="NV17435").locator("button:has-text('Ver PDF')").click()
    assert page.locator(".error").count() == 0
    print("2) Ver PDF abre pestaña sin error en la UI: OK")

    # 3. Facturas: columna Tipo con badge Equivalente en las reales
    page.goto("http://127.0.0.1:8000/facturas", wait_until="networkidle")
    page.wait_for_selector("table.tabla tbody tr", timeout=8000)
    expect(page.locator("table.tabla thead th", has_text="Tipo")).to_have_count(1)
    page.select_option(".filtros select >> nth=1", "EQUIVALENTE")  # 2º select = tipo
    expect(page.locator("table.tabla tbody tr", has_text="COL2051775")).to_have_count(1, timeout=8000)
    badges = page.locator("table.tabla tbody .badge.t-equivalente").count()
    filas_eq = page.locator("table.tabla tbody tr").count()
    # sin fijar el número: la ingesta real va sumando equivalentes con el tiempo
    assert filas_eq > 0 and badges == filas_eq, f"badges={badges} filas={filas_eq}"
    print(f"3) filtro Tipo=Equivalente muestra {filas_eq} filas, todas con badge: OK")

    page.select_option(".filtros select >> nth=1", "")
    # 4. filtro de fechas (emisión 2026-07-16 a 2026-07-16 debe incluir COL2026128)
    page.fill(".filtro-fecha input >> nth=0", "2026-07-16")
    page.fill(".filtro-fecha input >> nth=1", "2026-07-16")
    expect(page.locator("table.tabla tbody tr", has_text="COL2026128")).to_have_count(1, timeout=8000)
    # 6ª columna: la 1ª es la casilla de selección para quien puede aprobar
    textos = page.locator("table.tabla tbody td:nth-child(6)").all_inner_texts()
    assert all("16" in t for t in textos), f"fechas fuera de rango: {textos}"
    print(f"4) filtro de fechas: {len(textos)} facturas, todas emitidas el 16 jul: OK")

    # 5. limpiar fechas -> vuelven todas y la paginación resetea a 1
    page.fill(".filtro-fecha input >> nth=0", "")
    page.fill(".filtro-fecha input >> nth=1", "")
    expect(page.locator(".paginacion span")).to_contain_text("Página 1", timeout=8000)
    print("5) limpiar filtros resetea a página 1: OK")

    print("errores de consola:", len(errores))
    for e in errores:
        print("  -", e)
    b.close()

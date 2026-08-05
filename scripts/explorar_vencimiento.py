"""Spike (solo lectura): ¿el JSON del listado del portal trae la fecha de vencimiento?

Paso 1 del plan: loguea con SiesaClient (valida de paso el _login() adaptado a
v3.1.0.17), lista unos días de Facturas y imprime TODAS las claves del registro
crudo, marcando las que suenen a vencimiento/pago/plazo.

Uso: .venv/Scripts/python.exe scripts/explorar_vencimiento.py [dias]
"""
import json
import sys
from datetime import date, timedelta

sys.path.insert(0, "backend")

from app.config import settings  # noqa: E402
from app.ingesta.siesa_client import SiesaClient  # noqa: E402

dias = int(sys.argv[1]) if len(sys.argv) > 1 else 7
hasta = date.today()
desde = hasta - timedelta(days=dias)

SOSPECHOSAS = ("venc", "pago", "due", "plazo", "limite", "límite", "cobro")

with SiesaClient(settings.url_facturas, settings.username_facturas,
                 settings.password_facturas) as siesa:
    print(f"LOGIN OK (v3.1). Listando facturas {desde}..{hasta}...")
    docs = siesa.listar_documentos(desde.isoformat(), hasta.isoformat(), tipo_doc="1")
    print(f"El portal devolvió {len(docs)} facturas.\n")
    if not docs:
        print("Sin filas en el rango — amplía los días.")
        sys.exit(0)

    claves = sorted(docs[0].crudo.keys())
    print(f"CLAVES del registro crudo ({len(claves)}):")
    for k in claves:
        marca = "  <-- POSIBLE VENCIMIENTO" if any(s in k.lower() for s in SOSPECHOSAS) else ""
        print(f"  - {k}{marca}")

    print("\nPRIMEROS 2 REGISTROS COMPLETOS:")
    for d in docs[:2]:
        print(json.dumps(d.crudo, indent=2, ensure_ascii=False, default=str)[:3000])
        print("-" * 60)

"""Prueba de integración del SiesaClient contra el portal real."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import settings
from app.ingesta.siesa_client import SiesaClient

DEST = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("descargas/prueba_cliente")
DEST.mkdir(parents=True, exist_ok=True)

with SiesaClient(settings.url_facturas, settings.username_facturas, settings.password_facturas) as s:
    print("Login OK. Listando 2026-07-01..2026-07-17 ...")
    docs = s.listar_documentos("2026-07-01", "2026-07-17")
    print(f"Documentos: {len(docs)}")
    for d in docs[:5]:
        print(f"  {d.folio:12} | {d.emisor[:30]:30} | {d.valor} | {d.cufe[:16]}…")

    if docs:
        d0 = docs[0]
        print(f"\nDescargando PDF de {d0.folio} ...")
        pdf = s.descargar_pdf(d0.cufe)
        destino = DEST / f"{d0.nit_emisor}_{d0.folio}.pdf"
        destino.write_bytes(pdf)
        print(f"PDF guardado: {len(pdf)} bytes -> {destino}")

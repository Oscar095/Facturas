"""Spike de reconocimiento (solo lectura, no toca BD ni Blob): confirma si el
portal Siesa devuelve Notas Crédito (tipo_doc=91) y Documentos Equivalentes
(tipo_doc=20) en un rango de fechas, y si sus CUFE/folio vienen poblados.

Esto decide si _crear_nota_credito/_crear_factura necesitan normalizar CUFE
vacío antes de insertar (ver plan: un CUFE "" nunca se detecta como duplicado
y puede romper el UniqueConstraint en cadena, silenciosamente).

Uso: .venv/Scripts/python.exe scripts/explorar_tipos_documento.py [dias]
"""
import sys
from datetime import date, timedelta

sys.path.insert(0, "backend")

from app.config import settings  # noqa: E402
from app.ingesta.siesa_client import SiesaClient  # noqa: E402

dias = int(sys.argv[1]) if len(sys.argv) > 1 else 270
hasta = date.today().isoformat()
desde = (date.today() - timedelta(days=dias)).isoformat()
print(f"Rango: {desde} .. {hasta} ({dias} días)\n")

with SiesaClient(settings.url_facturas, settings.username_facturas,
                 settings.password_facturas, headless=True) as siesa:
    for tipo_doc, nombre in (("20", "Documentos Equivalentes"), ("91", "Notas Crédito")):
        print(f"=== {nombre} (tipo_doc={tipo_doc}) ===")
        docs = siesa.listar_documentos(desde, hasta, tipo_doc=tipo_doc)
        print(f"Total: {len(docs)}")
        vacios_cufe = sum(1 for d in docs if not d.cufe)
        vacios_folio = sum(1 for d in docs if not d.folio)
        print(f"Con CUFE vacío: {vacios_cufe}/{len(docs)}  |  Con folio vacío: {vacios_folio}/{len(docs)}")
        for d in docs[:5]:
            print(f"  folio={d.folio!r} cufe={d.cufe[:20]!r} fecha={d.fecha} valor={d.valor} "
                  f"nit={d.nit_emisor} tipo_documento_id={d.tipo_documento_id!r}")
        if docs:
            print(f"  crudo[0] = {docs[0].crudo}")
        print()

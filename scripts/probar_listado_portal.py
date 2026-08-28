"""Verifica el listado del portal SIN tocar BD ni Blob.

Existe porque el portal migró el listado a un endpoint cifrado y ahora las
filas se leen del scope de Angular: esta es la prueba de que esa lectura
sigue funcionando (y el primer sitio a mirar cuando la ingesta traiga 0).

Uso: .venv/Scripts/python.exe scripts/probar_listado_portal.py [dias]
"""
import sys
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, "backend")

from app.config import settings  # noqa: E402
from app.ingesta.siesa_client import SiesaClient  # noqa: E402

dias = int(sys.argv[1]) if len(sys.argv) > 1 else 7
hasta = date.today().isoformat()
desde = (date.today() - timedelta(days=dias)).isoformat()
print(f"Rango: {desde} .. {hasta} ({dias} días)\n")

fallos = 0
with SiesaClient(settings.url_facturas, settings.username_facturas,
                 settings.password_facturas, headless=True) as siesa:
    for tipo_doc, nombre in (("1", "Facturas"), ("20", "Documentos Equivalentes"),
                             ("91", "Notas Crédito")):
        docs = siesa.listar_documentos(desde, hasta, tipo_doc=tipo_doc)
        print(f"=== {nombre} (tipo_doc={tipo_doc}): {len(docs)} documentos ===")
        if not docs:
            print("   (ninguno en el rango — válido si de verdad no llegaron)\n")
            continue

        # los campos que la ingesta necesita SÍ o SÍ
        sin_cufe = [d for d in docs if not d.cufe]
        sin_folio = [d for d in docs if not d.folio]
        sin_valor = [d for d in docs if d.valor is None]
        sin_fecha = [d for d in docs if d.fecha is None]
        for etiqueta, faltantes in (("cufe", sin_cufe), ("folio", sin_folio),
                                    ("valor", sin_valor), ("fecha", sin_fecha)):
            if faltantes:
                fallos += 1
                print(f"   FALLO: {len(faltantes)}/{len(docs)} sin {etiqueta} "
                      f"(p. ej. {faltantes[0].folio or faltantes[0].id_portal})")

        # Ojo: el id que devuelve el portal NO es el del filtro. Con tipo_doc=20
        # (Documento Equivalente) los documentos vuelven con tipoDocumentoId 60
        # y 50 — son subtipos suyos, no una mezcla. Así que no se compara por
        # igualdad ni se exige un solo valor: se verifica que NO se hayan colado
        # documentos de los otros tipos que sí extraemos.
        AJENOS = {"1": {"91", "20", "50", "60"}, "91": {"1", "20", "50", "60"},
                  "20": {"1", "91"}}
        tipos = Counter(d.tipo_documento_id for d in docs)
        intrusos = set(tipos) & AJENOS.get(tipo_doc, set())
        if intrusos:
            fallos += 1
            print(f"   FALLO: el filtro dejó pasar otros tipos {intrusos} "
                  f"(llegaron {dict(tipos)})")
        elif tipo_doc not in tipos:
            print(f"   nota: el portal etiqueta este tipo como {sorted(tipos)}")

        cufes = [d.cufe for d in docs]
        if len(set(cufes)) != len(cufes):
            fallos += 1
            print(f"   FALLO: hay CUFE repetidos ({len(cufes) - len(set(cufes))}) "
                  "— la paginación está trayendo la misma página")

        d = docs[0]
        print(f"   muestra: folio={d.folio} nit={d.nit_emisor} valor={d.valor} "
              f"fecha={d.fecha} cufe={d.cufe[:16]}…")
        print(f"   emisores distintos: {len({x.emisor for x in docs})}\n")

print("TODO OK" if not fallos else f"{fallos} COMPROBACIONES FALLARON")
sys.exit(1 if fallos else 0)

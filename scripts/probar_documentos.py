"""OBSOLETO — NO CORRER. Se deja solo para que nadie lo resucite.

Venía de cuando el backend corría contra una BD de desarrollo: sube PDFs falsos
(`ocs.pdf`, `ocn.pdf`, `crn.pdf`) a las DOS PRIMERAS FACTURAS REALES del listado e
intenta contabilizar una. Contra Azure SQL de producción eso ensucia facturas de
verdad: el 2026-09-14 dejó una OCS falsa en FV11990, que pasó sola a
`lista_contabilizar`, y una OCN/CRN falsas en GF49586 (se revirtió a mano).

La prueba vigente del flujo de documentos, sobre una factura SINTÉTICA que se crea
y se limpia, es `scripts/probar_documentos_multiples_api.py`.
"""
raise SystemExit(
    "probar_documentos.py está obsoleto: escribe en facturas REALES. "
    "Usa scripts/probar_documentos_multiples_api.py."
)

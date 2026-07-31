"""Corre una ingesta real limitada para validar el flujo portal -> Blob -> SQL.

Uso: .venv/Scripts/python.exe scripts/probar_ingesta.py [limite] [dias]
`limite` aplica por separado a cada tipo (facturas+equivalentes / notas crédito).
Un conteo de 0 con errores=0 es válido (puede no haber documentos del tipo en el rango).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.database import SessionLocal  # noqa: E402
from app.ingesta.sincronizar import sincronizar  # noqa: E402

limite = int(sys.argv[1]) if len(sys.argv) > 1 else 3
dias = int(sys.argv[2]) if len(sys.argv) > 2 else 3
db = SessionLocal()
try:
    resumen = sincronizar(db, dias=dias, limite=limite)
    print("RESUMEN:")
    print(f"  estado: {resumen['estado']}  rango: {resumen['rango']}")
    print(f"  facturas/equivalentes nuevas: {resumen['facturas_nuevas']}")
    print(f"  notas crédito nuevas: {resumen['notas_credito_nuevas']}")
    print(f"  errores: {resumen['errores']}")
    for d in resumen["detalle"]:
        print(f"  - {d}")
finally:
    db.close()

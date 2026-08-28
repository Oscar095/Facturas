"""Regresión del ciclo de vida de SiesaClient.

Si `__enter__` falla (login lento, portal caído), Python NO llama a `__exit__`:
la sesión de Playwright quedaba viva y dejaba el hilo con un loop de asyncio
corriendo, así que la SIGUIENTE corrida en ese mismo hilo del threadpool moría
al instante con "Playwright Sync API inside the asyncio loop". Pasó en
producción: la ejecución #121 (login lento) tumbó a la #122.

No toca el portal real ni la BD: usa una URL inexistente para forzar el fallo.
Uso: .venv/Scripts/python.exe scripts/probar_cliente_ciclo_vida.py
"""
import sys

sys.path.insert(0, "backend")

from app.ingesta.siesa_client import SiesaClient  # noqa: E402

URL_MUERTA = "http://127.0.0.1:9/no-existe"  # puerto descartado: falla siempre

fallos = 0

# 1) un __enter__ que revienta debe dejar todo cerrado
cliente = SiesaClient(URL_MUERTA, "u", "c", headless=True)
try:
    with cliente:
        print("FALLO: el login no debió funcionar contra una URL muerta")
        fallos += 1
except Exception as e:
    print(f"1) __enter__ falla como se espera: {type(e).__name__}")

for attr in ("_pw", "_browser", "page"):
    valor = getattr(cliente, attr, "(sin atributo)")
    if valor is not None:
        fallos += 1
        print(f"   FALLO: {attr} quedó sin limpiar ({valor!r}) — la sesión se filtró")
if not fallos:
    print("2) tras el fallo no queda sesión de Playwright abierta: OK")

# 2) y el hilo debe quedar utilizable: un segundo cliente arranca sin problema
cliente2 = SiesaClient(URL_MUERTA, "u", "c", headless=True)
try:
    with cliente2:
        pass
except Exception as e:
    if "asyncio loop" in str(e):
        fallos += 1
        print(f"   FALLO: el hilo quedó envenenado por la sesión anterior: {e}")
    else:
        print(f"3) el segundo cliente vuelve a fallar por la URL (no por el hilo): "
              f"{type(e).__name__}: OK")

print("\nTODO OK" if not fallos else f"\n{fallos} COMPROBACIONES FALLARON")
sys.exit(1 if fallos else 0)

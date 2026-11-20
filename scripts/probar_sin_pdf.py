"""Regresión de la ingesta robusta (gotchas 14-17 de CLAUDE.md): un documento SIN PDF
no tumba la corrida, los listados se leen completos y una clave ya rechazada no se
vuelve a probar en las corridas automáticas.

Corre la ingesta real contra el portal Siesa, pero guarda en SQLite y almacén
LOCALES dentro de una carpeta temporal y sin IA: no toca Azure SQL, ni el Blob,
ni gasta créditos. Usa documentos reales del 2026-11:
  - FV70 y FE647: el proveedor los mandó sin PDF (el portal responde "-1" y abre
    el popup "¿Desea generar la factura web?"). FV70 va PRIMERO a propósito: si
    el popup quedara abierto, todo lo de después fallaría en cascada, que es lo
    que tuvo la ingesta caída del 2026-11-06 al 2026-11-20.
  - FE16727, FN27703 (facturas), COL2507939, POS2144 (equivalentes) y
    0201001620, NV18087 (notas crédito): tienen PDF y deben entrar.

Uso (desde la raíz del repo; entra al portal, ~2 min):
    .venv/Scripts/python.exe scripts/probar_sin_pdf.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# Antes de importar la app: sin estas variables, la config cae a SQLite y almacén
# local (y sin key no hay IA). load_dotenv no pisa variables que ya existen.
for var in ("BD_HOST", "SQL_SERVER", "AZURE_STORAGE_CONNECTION_STRING",
            "AZURE_STORAGE_ACCOUNT", "API_KEY_IA_CLAUDE", "ANTHROPIC_API_KEY"):
    os.environ[var] = ""
sys.path.insert(0, str(RAIZ / "backend"))
os.chdir(tempfile.mkdtemp(prefix="probar_sin_pdf_"))  # SQLite y descargas/ quedan aquí

from app.config import settings  # noqa: E402
from app.services.blob_storage import AlmacenLocal, get_almacen  # noqa: E402

if not settings.usa_sqlite or not isinstance(get_almacen(), AlmacenLocal) or settings.anthropic_api_key:
    sys.exit("ABORTADO: no quedó en modo local (SQLite + almacén local + sin IA)")

from app import models  # noqa: E402,F401 — registra las tablas
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.ingesta import siesa_client as sc  # noqa: E402
from app.ingesta.sincronizar import sincronizar  # noqa: E402
from app.models import Factura, NotaCredito  # noqa: E402

Base.metadata.create_all(engine)
print(f"Modo local OK en {os.getcwd()}\n")

ELEGIDOS = {"1": ["FV70", "FE16727", "FE647", "FN27703"],
            "20": ["COL2507939", "POS2144"],
            "91": ["0201001620", "NV18087"]}
_listar_real = sc.SiesaClient.listar_documentos


fallos: list[str] = []


def comprobar(cond: bool, que: str):
    print(("  ok   " if cond else "  FALLA ") + que)
    if not cond:
        fallos.append(que)


def _listar_solo_elegidos(self, desde, hasta, tipo_doc="1"):
    """El listado es el real (y se comprueba que se leyó entero); solo se recorta
    a los documentos de la prueba y se ordena para que el sin PDF vaya primero."""
    todos = _listar_real(self, desde, hasta, tipo_doc)
    comprobar(len(todos) == self.ultimo_total and len({d.cufe for d in todos}) == len(todos),
              f"tipo {tipo_doc}: se leyeron los {self.ultimo_total} que reporta el portal, "
              f"sin repetidos ({len(todos)} leídos)")
    orden = ELEGIDOS.get(tipo_doc, [])
    docs = sorted([d for d in todos if d.folio in orden], key=lambda d: orden.index(d.folio))
    self.ultimo_total = len(docs)  # el recorte es a propósito: que no cuente como incompleto
    return docs


print("=== 1) Corrida completa con un documento sin PDF de primero ===")
sc.SiesaClient.listar_documentos = _listar_solo_elegidos
db = SessionLocal()
t0 = time.time()
r = sincronizar(db, fecha_desde="2026-11-06", fecha_hasta="2026-11-20",
                usar_ia_vencimiento=False, usar_ia_iva=False)
sc.SiesaClient.listar_documentos = _listar_real
print(f"  ({time.time() - t0:.0f}s) fases: {r['fases']}")
comprobar(r["estado"] == "ok", f"estado ok (fue {r['estado']}; detalle: {r['detalle']})")
comprobar(sorted(r["sin_pdf"]) == ["Factura FE647", "Factura FV70"], f"sin PDF = FV70 y FE647 ({r['sin_pdf']})")
comprobar(r["facturas_nuevas"] == 4, f"4 facturas nuevas: 2 facturas + 2 equivalentes ({r['facturas_nuevas']})")
comprobar(r["notas_credito_nuevas"] == 2, f"2 notas crédito nuevas ({r['notas_credito_nuevas']})")
numeros = {f.numero: f for f in db.query(Factura).all()}
comprobar({"FE16727", "FN27703"} <= set(numeros), "entraron FE16727 y FN27703, que van DESPUÉS de FV70")
comprobar(all(f.blob_pdf and f.texto_pdf for f in numeros.values()), "todas con PDF y texto")
comprobar(sum(f.tipo_documento == "EQUIVALENTE" for f in numeros.values()) == 2, "2 equivalentes")
comprobar(db.query(NotaCredito).count() == 2, "2 notas crédito en su tabla")
db.close()

print("\n=== 2) Tope de 90 días, cuenta bloqueada y popup ===")
# respuesta real (cifrada) de /login/user-login del 2026-11-19, cuenta bloqueada
BLOQUEADA = ("Du9KmvQFbTT+S04McMM2PSzXYam8gVTV2GiYtbSVKhSWys7/bL99NHNxeUYSua/73qTZwk7k1QiAJm"
             "g+yjC/o7XYZj9HkEIWQIzUF6QRbZ38aRtFsKlgGYuhN8AQkkpj3Rh7H4saniIArI3Ak0bbLO79OF9c"
             "0qNeJVL5FFrFQ03eVjTXgUbfMP5MNl2GDtREVbkXOB6USg2qY6zTvdT+6G7gIqsgy1sOO3qwGfvMuy"
             "bg6ByI5GrlYsjxeiGZS3wk")


class _RespuestaGuardada:
    def text(self):
        return BLOQUEADA


with sc.SiesaClient(settings.url_facturas, settings.username_facturas,
                    settings.password_facturas) as s:
    try:
        s.listar_documentos("2026-08-01", "2026-11-20")
        comprobar(False, "un rango de más de 90 días se rechaza")
    except ValueError:
        comprobar(True, "un rango de más de 90 días se rechaza")
    motivo = s._rechazo_de_login({"user-login": _RespuestaGuardada()}, {}) or ""
    comprobar("bloqueada" in motivo, f"se lee el motivo real de un login rechazado ({motivo[:60]}…)")
    fv70 = next(d for d in s.listar_documentos("2026-11-18", "2026-11-18") if d.folio == "FV70")
    t0 = time.time()
    try:
        s.descargar_pdf(fv70.cufe, fv70.fecha, tipo_doc="1")
        comprobar(False, "FV70 lanza DocumentoSinPdf")
    except sc.DocumentoSinPdf:
        comprobar(time.time() - t0 < 20, f"FV70 lanza DocumentoSinPdf rápido ({time.time() - t0:.1f}s)")
    comprobar(s.page.evaluate(sc._JS_SWAL_TEXTO) is None, "no queda ningún popup abierto")
    # varias páginas de 100: ni repetidas ni faltantes (la búsqueda duplicada
    # del select#regist corría la paginación)
    largo = s.listar_documentos("2026-10-01", "2026-11-20", tipo_doc="1")
    comprobar(len(largo) == s.ultimo_total and len({d.cufe for d in largo}) == len(largo),
              f"listado de varias páginas completo y sin repetidos ({len(largo)} de {s.ultimo_total})")

print("\n=== 3) Clave ya rechazada: las corridas automáticas no la vuelven a probar ===")
from app.ingesta import sincronizar as sz  # noqa: E402
from app.models import Ejecucion, ahora  # noqa: E402

db = SessionLocal()
marca = sz._MARCA_RECHAZO.format(sz._huella_credencial())
db.add(Ejecucion(inicio=ahora(), fin=ahora(), estado="error",
                 detalle=f"Fallo general: El portal rechazó el login: Su cuenta se encuentra "
                         f"bloqueada (simulado) {marca}"))
db.commit()
_entrar_real = sc.SiesaClient.__enter__


def _no_debe_entrar(self):
    raise AssertionError("intentó entrar al portal con una clave ya rechazada")


sc.SiesaClient.__enter__ = _no_debe_entrar
try:
    r = sincronizar(db, dias=1, usar_ia_vencimiento=False, usar_ia_iva=False)
finally:
    sc.SiesaClient.__enter__ = _entrar_real
cabeza = r["detalle"][0] if r["detalle"] else ""
comprobar(r["estado"] == "error" and r["errores"] == 1, f"corrida en error con errores=1 ({r['estado']}, {r['errores']})")
comprobar("No se intentó entrar" in cabeza, f"no se intentó el login ({cabeza[:70]}…)")
comprobar(marca in (db.get(Ejecucion, r["ejecucion_id"]).detalle or ""),
          "la marca pasa a la corrida siguiente (hasta que cambie la clave)")
db.close()

print("\nTODO OK" if not fallos else f"\n{len(fallos)} COMPROBACIONES FALLARON")
sys.exit(1 if fallos else 0)

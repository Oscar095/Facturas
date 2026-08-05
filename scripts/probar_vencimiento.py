"""Prueba unitaria del extractor de vencimiento con fragmentos REALES de los
PDF de la BD (cada formato problemático observado). No toca la base de datos."""
import sys

sys.path.insert(0, "backend")
from datetime import datetime  # noqa: E402

from app.services.vencimiento import extraer_vencimiento  # noqa: E402

CASOS = [
    # (texto, fecha_emision, esperado)
    ("CONDICION DE PAGO 30017310 DO 31/8/2026 FECHA VENCIMIENTO 17/7/2026 FECHA FACTURA CALI 45 DIAS",
     datetime(2026, 7, 17), datetime(2026, 8, 31)),  # valor ANTES de la etiqueta (columnas)
    ("Expedición 17/07/2026, 14:24 Vencimiento 17/07/2026 Dólar estadounidense (USD)",
     datetime(2026, 7, 17), datetime(2026, 7, 17)),  # contado: venc = emisión
    ("Teléfono: 3102338779 Fecha de Vencimiento: 17-07-2026 E-mail: x@y.com",
     datetime(2026, 7, 17), datetime(2026, 7, 17)),  # guiones
    ("FECHA VENCIMIENTO PAGO DÍA MES AÑO HORA 24 07 2026 08:03 DATOS DE CLIENTE",
     datetime(2026, 7, 17), datetime(2026, 7, 24)),  # columnas DÍA MES AÑO
    ("CREDITO 45 DIAS FECHA VENCIMIENTO : 2026-SEP-06 EMAIL CLIENTE",
     datetime(2026, 7, 23), datetime(2026, 9, 6)),   # mes en letras (AAAA-MES-DD)
    # "Pague Antes De" como etiqueta (no dice "vencimiento") + mes en letras.
    # El layout parte el dato: la 1ª mención queda pegada a la EMISIÓN y la 2ª
    # al vencimiento — por eso el nivel 1 junta todas las apariciones.
    ("FORMA DE PAGO: CREDITO Fecha Emisión Factura: Pague Antes De: Factura "
     "electrónica No: FEC-36503 D M A D M A NIT: 21 Jul 2026 20 Ago 2026 "
     "901318511-7 ... Paguese Antes de 20 Ago 2026 BANCOLOMBIA",
     datetime(2026, 7, 21), datetime(2026, 8, 20)),
    ("Fecha vencimiento: 21/ago./2026 Orden de compra",
     datetime(2026, 7, 22), datetime(2026, 8, 21)),
    ("Fecha de Expedición 2026-07-21 Fecha de vencimiento 2026-07-21 Razón Social",
     datetime(2026, 7, 21), datetime(2026, 7, 21)),  # ISO
    ("Fecha Vencimiento: 2026-09-19 Fecha Generación: 2026-07-21 00:00:00",
     datetime(2026, 7, 21), datetime(2026, 9, 19)),
    ("22/07/202607/09/2026Fecha GeneraciónFecha Vencimiento FACTURA ELECTRONICA",
     datetime(2026, 7, 22), datetime(2026, 9, 7)),   # fechas pegadas antes de etiquetas
    ("Forma de Pago: CREDITO | Fecha de Vencimiento | | Contacto :",
     datetime(2026, 7, 20), None),                   # etiqueta sin valor ni plazo -> None
    ("Después de vencido el plazo para el pago de la presente Factura",
     datetime(2026, 7, 20), None),                   # mención legal sin fecha -> None
    # respaldo por plazo de crédito (no hay fecha impresa): emisión + N días
    ("Forma de pago: Medios de Pago:CREDITO 45 DIAS",
     datetime(2026, 7, 20), datetime(2026, 9, 3)),
    ("Condiciones de pago: Credito a 60 dias",
     datetime(2026, 7, 20), datetime(2026, 9, 18)),
    ("Plazo: 0 Dias", datetime(2026, 7, 20), datetime(2026, 7, 20)),
    ("CREDITO 45 DIAS", None, None),                 # sin emisión no se puede calcular
    # layout revuelto: etiqueta lejos del valor, pero una sola fecha futura
    ("Forma de Pago Fecha de Vencimiento Numero de Referencia ... Resolución 2025-05-13 "
     "hasta 2027-05-13 ... Emitida 2026-08-05 ... 2026-10-04 total a pagar",
     datetime(2026, 8, 5), datetime(2026, 10, 4)),
    # ...pero si hay varias fechas futuras (lejos de la etiqueta) es ambiguo -> None
    ("Fecha de Vencimiento Numero de Referencia Codigo Banco Cuenta" + " x" * 90
     + " entrega 2026-09-01 despacho 2026-10-04 total a pagar",
     datetime(2026, 8, 5), None),
    # la vigencia de la resolución DIAN no debe confundirse con el vencimiento
    ("Fecha de Vencimiento: Resolución vigente desde 2025-05-13 hasta 2027-05-13",
     datetime(2026, 8, 5), None),
    ("texto sin nada relevante", datetime(2026, 7, 20), None),
    ("", None, None),
    (None, None, None),
]

fallos = 0
for texto, emision, esperado in CASOS:
    obtenido = extraer_vencimiento(texto, emision)
    ok = obtenido == esperado
    if not ok:
        fallos += 1
    print(f"{'OK ' if ok else 'FALLO'} esperado={esperado} obtenido={obtenido}  <- {(texto or '')[:60]!r}")

print(f"\n{len(CASOS) - fallos}/{len(CASOS)} casos correctos")
sys.exit(1 if fallos else 0)

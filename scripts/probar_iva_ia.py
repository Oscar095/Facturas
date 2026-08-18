"""Prueba del guardarraíl de la capa IA del IVA, con respuestas REALES que dio
Haiku sobre facturas de la BD. No llama a la API ni toca la base de datos:
ejercita el parseo de la respuesta y `_aceptable`, que es lo que decide si una
cifra entra o se descarta."""
import sys

sys.path.insert(0, "backend")
from decimal import Decimal  # noqa: E402

from app.services.iva_ia import _aceptable, _cifras  # noqa: E402

D = Decimal


def veredicto(respuesta: str, total: Decimal, texto: str = "", hay_texto: bool | None = None):
    """Replica lo que hace sugerir_iva con la respuesta cruda del modelo."""
    if not respuesta or respuesta.upper().startswith("NULL"):
        return None
    if hay_texto is None:
        hay_texto = bool(texto)
    partes = respuesta.split("|")
    if len(partes) < 2:
        return None
    bases, ivas = _cifras(partes)
    for base in bases:
        for iva in ivas:
            if _aceptable(base, iva, total, texto, hay_texto):
                return iva.quantize(D("0.01"))
    return None


CASOS = [
    # ── ACEPTAR: la suma reconcilia con el total que entrega el portal ──
    # separadores "al revés": 104200.00 no debe leerse como 10.420.000
    ("104200.00|19798.00|TOTAL ITEMS: 4 Acuerdo mutuo 104,200.00 / 19,798.00 / 123,998.00",
     D("123998.00"), "Acuerdo mutuo 104,200.00 19,798.00 123,998.00", D("19798.00")),
    # tarifa mezclada (parte gravada, parte exenta): 1,9% global, imposible por regex
    ("68.621.611|1.303.811|Subtotal: 68.621.611 ... IVA 19,00% 1.303.811",
     D("69925422.00"), "Subtotal: 68.621.611 IVA 19,00% 1.303.811", D("1303811.00")),
    ("2.061.468|20.687|SUBTOTAL 2.061.468 COP / IVA 20.687 COP",
     D("2082155.00"), "SUBTOTAL 2.061.468 COP IVA 20.687 COP", D("20687.00")),
    ("$2.932.206,23|$132.819,92|IVABaseTasa19,0%Valor$132.819,92",
     D("3065026.15"), "IVA Base Tasa 19,0% Valor $132.819,92", D("132819.92")),
    # escaneada (sin texto): un IVA de 0 leído del documento se acepta
    ("2000000|0|Subtotal $ 2.000.000 / Iva $ 0", D("2000000.00"), "", D("0.00")),
    # escaneada al 19%: la vía gratis no puede verla (no hay texto donde buscar
    # el importe), la IA sí — y la suma confirma la lectura
    ("270600.00|51414.00|Total sin impuestos $ 270,600.00 / IVA Ventas 19% $ 51,414.00",
     D("322014.00"), "", D("51414.00")),

    # el modelo repite las etiquetas del formato pedido antes de las cifras
    ("base|iva|20,000.00|0.00|Base: 20,000.00 / Impuestos: 0.00",
     D("20000.00"), "", D("0.00")),
    ("base|iva|14166.67|1133.33|SUBTOTAL 14,166.67 / TOTAL I.V.A 1,133.33",
     D("15300.00"), "", D("1133.33")),
    # punto como separador de miles Y de decimales en el mismo número
    ("680.943.00|129.379.17|Valor Base 680.943.00 / IMPUESTO A LAS VENTAS 19%",
     D("810322.17"), "", D("129379.17")),

    # ── DESCARTAR ──
    # el modelo tomó el IVA de UN renglón de una factura de 73 millones
    ("$196.158,60|$37.270,13|IVA Base $196.158,60 Tasa 19,0% Valor $37.270,13",
     D("73561959.67"), "", None),

    # invención típica: el 19% exacto que NO está impreso en el texto
    ("1000000|190000|IVA 19%", D("1190000.00"),
     "Servicios profesionales. Total 1.190.000. No responsable de IVA.", None),
    # ...pero si ese mismo importe SÍ está impreso, se acepta
    ("1000000|190000|IVA 19% 190.000", D("1190000.00"),
     "Subtotal 1.000.000 IVA 19% 190.000 Total 1.190.000", D("190000.00")),
    # gravamen arancelario de una importación: la tarifa se dispara
    ("259814|350155|IVA GRAVAMEN 331,000.00", D("609969.00"), "", None),
    # el modelo se niega, que es lo correcto cuando la factura no lo discrimina
    ("NULL", D("753000.00"), "SUBTOTAL I.V.A NETO A PAGAR", None),
    ("NULL\n\nLa factura no discrimina el IVA.", D("13654400.00"), "", None),
    # basura
    ("no lo sé", D("100000.00"), "", None),
    ("", D("100000.00"), "", None),
]

fallos = 0
for respuesta, total, texto, esperado in CASOS:
    obtenido = veredicto(respuesta, total, texto)
    ok = obtenido == esperado
    if not ok:
        fallos += 1
    print(f"{'OK ' if ok else 'FALLO'} esperado={esperado} obtenido={obtenido}"
          f"  <- {respuesta[:52]!r}")

print(f"\n{len(CASOS) - fallos}/{len(CASOS)} casos correctos")
sys.exit(1 if fallos else 0)

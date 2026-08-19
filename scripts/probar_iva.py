"""Prueba unitaria del extractor de IVA con fragmentos REALES de los PDF de la
BD (un caso por formato problemático observado) y con el total en sus dos tipos:
Decimal (como lo devuelve la BD) y float (como lo entrega la ingesta del portal).
No toca la base de datos."""
import sys

sys.path.insert(0, "backend")
from decimal import Decimal  # noqa: E402

from app.services.iva import extraer_iva  # noqa: E402

D = Decimal

CASOS = [
    # (texto, valor_total, iva esperado)
    # ── nivel 1: la tarifa reconcilia y el importe está impreso ──
    ("TOTALES USD COP Total Bruto 280.00 927,194.80 IVA 19% SERVICIOS 53.20 176,167.01 "
     "Retefuente 4% 11.20 37,087.80 Total a Pagar",
     D("1103361.81"), D("176167.01")),
    ("SUBTOTAL: VALOR I.V.A: TOTAL: 684,000 129,960 813,960 OCHOCIENTOS TRECE MIL",
     D("813960.00"), D("129960.00")),
    # separadores al revés (miles con punto, decimales con coma)
    ("Subtotal 1.785.000,00 Iva 19% 339.150,00 Total 2.124.150,00",
     D("2124150.00"), D("339150.00")),
    # tarifa del 5%
    ("Base 1.000.000 IVA 5% 50.000 Total 1.050.000", D("1050000.00"), D("50000.00")),
    # el redondeo del proveedor no debe tumbar la reconciliación
    ("Subtotal 576.818,49 IVA 109.595,51 Total 686.414,00",
     D("686414.00"), D("109595.51")),

    # ── nivel 2: el total impreso como base => sin IVA ──
    ("No responsable de IVA - Actividad Económica 7020 Adjunto soporte de pago "
     "Total Bruto 1,530,000.00 Total a Pagar 1,530,000.00",
     D("1530000.00"), D("0.00")),
    # el "Total a pagar" es MENOR por retefuente: la resta no es IVA
    ("POSTOBON AMAGA Subtotal Rete Fuente Iva Rete Ica $ 1.870.000 Total $ 1.851.300 "
     "VALOR EN LETRAS UN MILLON",
     D("1870000.00"), D("0.00")),
    ("Subtotal: 866.807 Esta Factura de Venta Electrónica está reglamentada ... IVA 0,00 %",
     D("866807.00"), D("0.00")),
    ("| SUB-TOTAL | VALOR_IVA | VALOR_RTEFTE | T O T A L | | 827,302.00 | 0.00 | 0.00 | "
     "827,302.00 |",
     D("827302.00"), D("0.00")),

    # ── casos que DEBEN quedar en None (no adivinar) ──
    # importes de flete/manejo cerca de la palabra IVA que no reconcilian
    ("GRAVAMEN ARANCELARIO 159,000.00 IVA GRAVAMEN 331,000.00 SERVICIOS DE ENTREGA "
     "MANEJO 100,814.00 BASE DE IVA 100,814.00 IVA 19 % 19,155.00 VALOR TOTAL DE LAS "
     "OPERACIONES 609,969.00",
     D("609969.00"), None),
    # solo menciones de régimen, ningún importe
    ("Somos Grandes Contribuyentes, Regimen Común, Responsables IVA. Somos Autoretenedores",
     D("11295469.43"), None),
    # cabeceras sin valores (layout que perdió los números)
    ("Firma Digital: Valor en LetrasSUBTOTALI.V.ANETO A PAGARCERO PESOS",
     D("753000.00"), None),
    ("texto sin nada relevante", D("100000.00"), None),
    ("Subtotal 1.000.000 IVA 190.000 Total 1.190.000", None, None),  # sin total
    (None, D("1190000.00"), None),
    ("", D("1190000.00"), None),
    ("Subtotal 0 Total 0", D("0"), None),  # total cero: nada que repartir

    # ── REGRESIÓN: el portal entrega el total como float, no como Decimal ──
    # Mezclarlos reventaba con TypeError y tumbó 2 facturas de una corrida real
    # (ejecución #86). La BD sí devuelve Decimal, por eso el backfill no lo vio.
    ("SUBTOTAL: VALOR I.V.A: TOTAL: 684,000 129,960 813,960", 813960.0, D("129960.00")),
    ("Total Bruto 1,530,000.00 Total a Pagar 1,530,000.00", 1530000.0, D("0.00")),
    ("Subtotal 1.785.000,00 Iva 19% 339.150,00", 2124150.0, D("339150.00")),
]

fallos = 0
for texto, total, esperado in CASOS:
    obtenido = extraer_iva(texto, total)
    ok = obtenido == esperado
    if not ok:
        fallos += 1
    print(f"{'OK ' if ok else 'FALLO'} esperado={esperado} obtenido={obtenido}"
          f"  <- {(texto or '')[:55]!r}")

print(f"\n{len(CASOS) - fallos}/{len(CASOS)} casos correctos")
sys.exit(1 if fallos else 0)

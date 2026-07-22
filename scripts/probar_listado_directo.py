"""Prueba el endpoint de listado por HTTP directo, con y sin cookies de sesión.

Uso:
    python scripts/probar_listado_directo.py <carpeta_con_cookies.json>
"""
import json
import sys
from pathlib import Path

import httpx

CARPETA = Path(sys.argv[1])

API_LISTADO = (
    "https://portalfe.siesacloud.com/PortalPTBack/frontend/web/index.php/"
    "pst/listado/recepcion-proveedores"
)

DATOS = {
    "filters[adquiriente]": "", "filters[consultaVersion]": "2.1",
    "filters[costCentersClient]": "", "filters[cufe]": "",
    "filters[estadoAdquiriente]": "", "filters[estadoDian]": "",
    "filters[facturador]": "", "filters[facturadorSelected]": "",
    "filters[fecha_desde]": "2026-07-01T00:00:00.000Z",
    "filters[fecha_hasta]": "2026-07-17T23:59:59.000Z",
    "filters[folio]": "", "filters[formaPago]": "3",
    "filters[isMaster]": "false", "filters[isOwner]": "false",
    "filters[nit]": "", "filters[nitAdquiriente]": "",
    "filters[operatingCenterId]": "", "filters[tipoDocRecepcion]": "1",
    "id": "", "itemSize": "100", "nit": "901318511", "numPage": "1",
    "userId": "30729",
    "usuarioEvento": "30729;LINA MARIA GARCIA REYES;linag@koscolombia.com",
}


def probar(nombre: str, client: httpx.Client):
    r = client.post(API_LISTADO, data=DATOS, timeout=60)
    resumen = {"status": r.status_code}
    try:
        j = r.json()
        resumen["totalItems"] = j.get("totalItems")
        resumen["folios"] = [f["folio"] for f in j.get("list", [])][:10]
    except Exception:
        resumen["texto"] = r.text[:400]
    print(f"[{nombre}] {json.dumps(resumen, ensure_ascii=False)}")
    (CARPETA / f"listado_directo_{nombre}.json").write_text(
        r.text, encoding="utf-8"
    )


with httpx.Client() as c:
    probar("sin_cookies", c)

cookies = json.loads((CARPETA / "cookies.json").read_text(encoding="utf-8"))
jar = httpx.Cookies()
for ck in cookies:
    jar.set(ck["name"], ck["value"], domain=ck["domain"])
with httpx.Client(cookies=jar) as c:
    probar("con_cookies", c)

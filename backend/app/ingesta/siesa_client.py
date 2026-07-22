"""Cliente del portal Siesa Smart4B.

Estrategia (validada contra el portal real):
  1. Login con Playwright (SPA Angular).
  2. Listado: al hacer la primera búsqueda en la UI capturamos el request
     `pst/listado/recepcion-proveedores` como plantilla; luego paginamos por
     HTTP reusando la sesión del navegador (page.request), sin depender de
     valores fijos por cuenta (userId, nit, usuarioEvento salen de la plantilla).
  3. PDF: se filtra por CUFE, se hace clic en "Ver PDF" y se capturan los bytes
     de la respuesta `siesafe...:707/api/ConsultaCO/pdf-recepcion` (application/pdf).

Uso típico:
    with SiesaClient(url, usuario, clave) as siesa:
        docs = siesa.listar_documentos("2026-07-01", "2026-07-17")
        pdf = siesa.descargar_pdf(cufe)
"""
from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime

from playwright.sync_api import Page, sync_playwright

API_LISTADO_PATH = "pst/listado/recepcion-proveedores"
PDF_URL_FRAGMENT = "pdf-recepcion"


@dataclass
class DocumentoPortal:
    """Un documento tal como lo entrega el listado del portal."""

    id_portal: str
    cufe: str
    folio: str            # número/prefijo del documento (ej. FE1548)
    nit_emisor: str
    emisor: str
    valor: float | None
    fecha: datetime | None
    estado_adquiriente: str
    forma_pago: str
    tipo_documento_id: str
    crudo: dict           # el registro JSON completo del portal


def _a_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _a_fecha(v) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v), fmt)
        except (TypeError, ValueError):
            continue
    return None


class SiesaClient:
    def __init__(self, url: str, usuario: str, clave: str, headless: bool = True):
        self.url = url.strip()
        self.usuario = usuario.strip()
        self.clave = clave.strip()
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None
        self.page: Page | None = None
        self._plantilla_listado: dict[str, str] | None = None

    # ── ciclo de vida ────────────────────────────────────────────────────────
    def __enter__(self) -> "SiesaClient":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(locale="es-CO", accept_downloads=True)
        self.page = self._context.new_page()
        self._login()
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    # ── login ────────────────────────────────────────────────────────────────
    def _login(self):
        p = self.page
        p.goto(self.url, wait_until="networkidle", timeout=60000)
        time.sleep(2)
        p.locator(
            "input[type='email'], input[type='text'], input[name*='user' i], "
            "input[placeholder*='usuario' i], input[placeholder*='correo' i]"
        ).first.fill(self.usuario)
        p.locator("input[type='password']").first.fill(self.clave)
        try:
            p.locator("button[type='submit']:visible").first.click(timeout=8000)
        except Exception:
            p.locator("input[type='password']").first.press("Enter")
        p.wait_for_url("**/documentRecepcion/**", timeout=45000)
        p.wait_for_load_state("networkidle", timeout=45000)
        time.sleep(2)

    # ── plantilla del listado ─────────────────────────────────────────────────
    def _capturar_plantilla(self, fecha_desde: str, fecha_hasta: str):
        """Hace una búsqueda en la UI para capturar el post_data del listado.

        Devuelve un dict de parámetros que luego modificamos por página.
        """
        p = self.page
        p.locator("input[placeholder*='Desde' i]").first.fill(fecha_desde.replace("-", "/"))
        p.locator("input[placeholder*='Hasta' i]").first.fill(fecha_hasta.replace("-", "/"))
        with p.expect_request(f"**/{API_LISTADO_PATH}", timeout=60000) as req_info:
            p.locator("button:has-text('Buscar')").first.click()
        post_data = req_info.value.post_data or ""
        params = dict(urllib.parse.parse_qsl(post_data, keep_blank_values=True))
        # normalizar fechas a rango ISO (el portal acepta el formato ISO con Z)
        params["filters[fecha_desde]"] = f"{fecha_desde}T00:00:00.000Z"
        params["filters[fecha_hasta]"] = f"{fecha_hasta}T23:59:59.000Z"
        params["filters[formaPago]"] = "3"   # sin filtrar por forma de pago
        params["itemSize"] = "100"
        self._plantilla_listado = params
        p.wait_for_load_state("networkidle", timeout=60000)
        time.sleep(1)

    # ── listado ────────────────────────────────────────────────────────────────
    def listar_documentos(
        self, fecha_desde: str, fecha_hasta: str, tipo_doc: str = "1"
    ) -> list[DocumentoPortal]:
        """Lista todos los documentos del rango (paginando). Fechas 'YYYY-MM-DD'.

        tipo_doc: 1=Factura, 91=Nota Crédito, 92=Nota Débito, 20=Doc Equivalente.
        """
        if self._plantilla_listado is None:
            self._capturar_plantilla(fecha_desde, fecha_hasta)

        base_url = self._url_api(API_LISTADO_PATH)
        params = dict(self._plantilla_listado)
        params["filters[fecha_desde]"] = f"{fecha_desde}T00:00:00.000Z"
        params["filters[fecha_hasta]"] = f"{fecha_hasta}T23:59:59.000Z"
        params["filters[tipoDocRecepcion]"] = tipo_doc

        docs: list[DocumentoPortal] = []
        num_page = 1
        while True:
            params["numPage"] = str(num_page)
            resp = self.page.request.post(
                base_url,
                form=params,
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=60000,
            )
            data = resp.json()
            lote = data.get("list", []) or []
            for r in lote:
                docs.append(self._mapear(r))
            total_pages = int(data.get("totalPages", 1) or 1)
            if num_page >= total_pages or not lote:
                break
            num_page += 1
        return docs

    @staticmethod
    def _mapear(r: dict) -> DocumentoPortal:
        return DocumentoPortal(
            id_portal=str(r.get("ID", "")),
            cufe=r.get("cufe", "") or "",
            folio=r.get("folio", "") or "",
            nit_emisor=str(r.get("nitFacturador", "") or ""),
            emisor=r.get("emisor", "") or "",
            valor=_a_float(r.get("valor")),
            fecha=_a_fecha(r.get("fecha")),
            estado_adquiriente=str(r.get("estadoAdquiriente", "") or ""),
            forma_pago=str(r.get("FORMA_PAGO", "") or ""),
            tipo_documento_id=str(r.get("tipoDocumentoId", "") or ""),
            crudo=r,
        )

    # ── modales ──────────────────────────────────────────────────────────────
    def _cerrar_modales(self):
        """Cierra cualquier modal abierto y elimina backdrops residuales.

        El portal muestra modales (validación de documento, visor de PDF) que,
        si un PDF tarda más de la cuenta y queda uno abierto, tapan el botón
        'Buscar' del siguiente documento y hacen fallar toda la corrida en
        cascada. Se cierra defensivamente antes de cada descarga.
        """
        p = self.page
        sel = ".modal.in, .modal.show, [uib-modal-window]"
        # 1) intento amable: botón de cierre / Escape (deja limpio el stack de Angular)
        for _ in range(3):
            if p.locator(sel).count() == 0:
                break
            try:
                p.locator(f"{sel} button.close, {sel} button[data-dismiss='modal']").first.click(timeout=1500)
            except Exception:
                try:
                    p.keyboard.press("Escape")
                except Exception:
                    pass
            p.wait_for_timeout(400)
        # 2) red de seguridad: ocultar cualquier modal/backdrop residual que siga
        #    interceptando clics (un modal atascado tapa el botón 'Buscar' del
        #    siguiente documento y tumba la corrida en cascada)
        p.evaluate(
            """() => {
                document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
                document.querySelectorAll('[uib-modal-window], .modal.in, .modal.show').forEach(m => {
                    m.style.display = 'none';
                    m.classList.remove('in', 'show');
                });
                document.body.classList.remove('modal-open');
                document.body.style.removeProperty('padding-right');
            }"""
        )

    # ── descarga de PDF ────────────────────────────────────────────────────────
    def descargar_pdf(self, cufe: str) -> bytes:
        """Filtra por CUFE, abre 'Ver PDF' y devuelve los bytes del PDF."""
        p = self.page
        self._cerrar_modales()  # limpiar cualquier modal dejado por el doc anterior
        caja_cufe = p.locator("input[placeholder*='CUFE' i]").first
        caja_cufe.fill("")
        caja_cufe.fill(cufe)
        p.locator("button:has-text('Buscar')").first.click()
        p.wait_for_load_state("networkidle", timeout=60000)
        time.sleep(2)
        if p.locator("table tbody tr").count() == 0:
            raise RuntimeError(f"El portal no devolvió filas para el CUFE {cufe[:16]}…")

        fila = p.locator("table tbody tr").first
        fila.locator("button.btn-default-drop").click()
        time.sleep(0.5)
        with self.page.expect_response(
            lambda r: PDF_URL_FRAGMENT in r.url
            and "application/pdf" in r.headers.get("content-type", ""),
            timeout=45000,
        ) as resp_info:
            fila.locator("a:has-text('Ver PDF')").click()
        body = resp_info.value.body()
        if not body or body[:4] != b"%PDF":
            raise RuntimeError("La respuesta no es un PDF válido")
        # limpiar el filtro para la siguiente descarga
        caja_cufe.fill("")
        return body

    # ── util ───────────────────────────────────────────────────────────────────
    def _url_api(self, path: str) -> str:
        # https://portalfe.siesacloud.com/PortalPTBack/frontend/web/index.php/<path>
        return f"https://portalfe.siesacloud.com/PortalPTBack/frontend/web/index.php/{path}"

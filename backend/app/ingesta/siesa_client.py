"""Cliente del portal Siesa Smart4B.

Estrategia (validada contra el portal real):
  1. Login con Playwright (SPA Angular).
  2. Listado: se maneja la UI (filtros + botón Buscar) y se leen las filas
     **ya descifradas** desde el scope de AngularJS (`$ctrl.document.list`).
     Antes se paginaba por HTTP contra `pst/listado/recepcion-proveedores`,
     pero el portal migró el listado a `api/SpExecute/execute` con
     `x-payload-encryption: true` — cuerpo y respuesta cifrados en el
     navegador, igual que el PDF. Ver el gotcha 7 en CLAUDE.md.
  3. PDF: se filtra por CUFE, se hace clic en "Ver PDF" y se capturan los bytes
     de la respuesta `siesafe...:707/api/ConsultaCO/pdf-recepcion` (application/pdf).

Uso típico:
    with SiesaClient(url, usuario, clave) as siesa:
        docs = siesa.listar_documentos("2026-07-01", "2026-07-17")
        pdf = siesa.descargar_pdf(cufe)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from playwright.sync_api import Page, sync_playwright

PDF_URL_FRAGMENT = "pdf-recepcion"

# Ancla para llegar al controlador de la pantalla de recepción desde JS. Se
# prueban varios elementos porque la fila del listado NO existe cuando la
# búsqueda no devuelve resultados, y ahí igual hay que poder leer el estado.
_JS_CTRL = """
  const anclas = ['tr[ng-repeat*="$ctrl.document.list"]', 'select#regist',
                  'select#tipoDocRecepcion', '[uib-pagination]'];
  let ctrl = null, sc = null;
  for (const sel of anclas) {
    const el = document.querySelector(sel);
    if (!el) continue;
    let s;
    try { s = window.angular.element(el).scope(); } catch (e) { continue; }
    if (s && s.$ctrl && s.$ctrl.document !== undefined) { ctrl = s.$ctrl; sc = s; break; }
  }
"""

# Fijar los filtros por el MODELO de Angular y no tecleando en el input: los
# inputs son de texto con datepicker propio y el valor tecleado se pierde, así
# que la grilla se quedaba mostrando solo el día de hoy (se veían 8 documentos
# donde había 102). `filters.fecha_desde`/`fecha_hasta` esperan objetos Date.
_JS_FIJAR_FILTROS = "(f) => {" + _JS_CTRL + """
  if (!ctrl || !sc) return false;
  const aplicar = () => {
    if (f.desde) ctrl.filters.fecha_desde = new Date(f.desde);
    if (f.hasta) ctrl.filters.fecha_hasta = new Date(f.hasta);
    if (f.tipo_doc !== null && f.tipo_doc !== undefined) ctrl.filters.tipoDocRecepcion = f.tipo_doc;
    ctrl.filters.cufe = f.cufe || '';
    ctrl.currentPage = 1;
  };
  try { sc.$apply(aplicar); } catch (e) { aplicar(); sc.$applyAsync(); }
  return true;
}"""

_JS_ESTADO = "() => {" + _JS_CTRL + """
  if (!ctrl) return null;
  return {
    cargando: !!ctrl.loading,
    pagina: Number(ctrl.currentPage) || 1,
    paginas: Number(ctrl.totalPages) || 1,
    total: Number(ctrl.totalItems) || 0,
    filas: (ctrl.document && ctrl.document.list) ? ctrl.document.list : [],
  };
}"""


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
    # El portal pasó a entregar la fecha en ISO con 'T' ("2026-08-26T00:00:00",
    # a veces con fracción de segundo); antes venía con espacio. Se aceptan
    # ambas para no depender de la versión del portal.
    if v is None:
        return None
    texto = str(v).strip()
    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, fmt)
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
        # v3.1.0.17: el botón de login ya no es type=submit (llama $ctrl.getToken());
        # se intenta por texto, luego el submit clásico y por último Enter.
        for enviar in (
            lambda: p.locator("button:has-text('Iniciar Sesión'):visible").first.click(timeout=5000),
            lambda: p.locator("button[type='submit']:visible").first.click(timeout=3000),
            lambda: p.locator("input[type='password']").first.press("Enter"),
        ):
            try:
                enviar()
                break
            except Exception:
                continue
        # v3.1 ya NO navega a **/documentRecepcion/** (la pantalla de recepción se
        # renderiza dejando la URL en #/login), así que esperar la URL rompía el
        # login aun con credenciales válidas. La señal confiable de sesión adentro
        # es que aparezca el botón Buscar de los filtros de búsqueda.
        p.locator("button:has-text('Buscar')").first.wait_for(state="visible", timeout=45000)
        p.wait_for_load_state("networkidle", timeout=45000)
        time.sleep(2)

    # ── estado del listado (leído del scope de Angular) ───────────────────────
    def _estado_listado(self) -> dict | None:
        """Filas ya descifradas + paginación, directo del controlador Angular."""
        return self.page.evaluate(_JS_ESTADO)

    def _esperar_listado(self, pagina: int = 1, timeout: float = 90.0) -> dict:
        """Espera a que termine la consulta y devuelve el estado del listado.

        No sirve `wait_for_load_state('networkidle')`: la SPA mantiene tráfico
        de fondo. Se espera a que `$ctrl.loading` baje y a que el controlador
        esté en la página pedida.
        """
        limite = time.time() + timeout
        ultimo: dict | None = None
        while time.time() < limite:
            estado = self._estado_listado()
            if estado is not None:
                ultimo = estado
                if not estado["cargando"] and estado["pagina"] == pagina:
                    return estado
            time.sleep(0.5)
        if ultimo is None:
            raise RuntimeError(
                "No se pudo leer el listado del portal: no se encontró el controlador "
                "de la pantalla de recepción (¿cambió la SPA otra vez?)"
            )
        return ultimo

    def _fijar_tamano_pagina(self, registros: str = "100"):
        """Pone la grilla en 100 registros por página (menos vueltas de paginación)."""
        sel = self.page.locator("select#regist").first
        if sel.count() and sel.input_value() != registros:
            try:
                sel.select_option(registros)
                time.sleep(0.3)
            except Exception:  # noqa: BLE001 — si el portal no ofrece 100, se sigue igual
                pass

    def _limpiar_filtro_cufe(self):
        """La descarga de PDF deja el CUFE escrito; si no se borra, el listado
        siguiente devuelve una sola fila."""
        caja = self.page.locator("input[placeholder*='CUFE' i]").first
        if caja.count():
            caja.fill("")

    # ── listado ────────────────────────────────────────────────────────────────
    def listar_documentos(
        self, fecha_desde: str, fecha_hasta: str, tipo_doc: str = "1"
    ) -> list[DocumentoPortal]:
        """Lista todos los documentos del rango (paginando). Fechas 'YYYY-MM-DD'.

        tipo_doc: 1=Factura, 91=Nota Crédito, 92=Nota Débito, 20=Doc Equivalente.

        Se maneja la UI y se leen las filas del scope de Angular: el endpoint
        del listado va cifrado y no se puede llamar por HTTP (ver el docstring
        del módulo).
        """
        p = self.page
        self._cerrar_modales()
        self._fijar_tipo_documento(tipo_doc)
        # el CUFE se limpia aquí mismo: si quedó del PDF anterior, el listado
        # devolvería una sola fila
        self._fijar_rango_fecha(datetime.fromisoformat(fecha_desde),
                                datetime.fromisoformat(fecha_hasta),
                                tipo_doc=tipo_doc, cufe="")
        self._fijar_tamano_pagina()

        p.locator("button:has-text('Buscar')").first.click()
        estado = self._esperar_listado(pagina=1)

        docs: list[DocumentoPortal] = [self._mapear(r) for r in estado["filas"]]
        paginas = max(1, estado["paginas"])
        for pagina in range(2, paginas + 1):
            # el paginador de uib expone el "siguiente" como <li class="pagination-next">
            siguiente = p.locator("li.pagination-next a").first
            if not siguiente.count():
                break
            siguiente.click()
            estado = self._esperar_listado(pagina=pagina)
            if estado["pagina"] != pagina:  # el portal no avanzó: no seguir en falso
                break
            docs += [self._mapear(r) for r in estado["filas"]]
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

    # ── filtro de fecha ────────────────────────────────────────────────────────
    def _fijar_rango_fecha(self, desde: datetime, hasta: datetime,
                           tipo_doc: str | None = None, cufe: str = ""):
        """Fija el rango de fechas (y opcionalmente tipo/CUFE) de la grilla.

        Se escribe el MODELO de Angular, no el input: el campo es de texto con
        datepicker propio y lo tecleado se pierde, así que la grilla se quedaba
        en 'hoy' — se veían 8 documentos donde había 102. Si el modelo no está
        accesible se cae al método viejo (teclear + eventos input/change).
        """
        ok = self.page.evaluate(_JS_FIJAR_FILTROS, {
            "desde": desde.strftime("%Y-%m-%dT00:00:00"),
            "hasta": hasta.strftime("%Y-%m-%dT23:59:59"),
            "tipo_doc": tipo_doc,
            "cufe": cufe,
        })
        if ok:
            return

        p = self.page
        for sel, valor in (("input[placeholder*='Desde' i]", desde),
                           ("input[placeholder*='Hasta' i]", hasta)):
            loc = p.locator(sel).first
            loc.click()
            loc.fill("")
            loc.type(valor.strftime("%Y/%m/%d"), delay=20)
            loc.evaluate(
                "el => { el.dispatchEvent(new Event('input',{bubbles:true}));"
                " el.dispatchEvent(new Event('change',{bubbles:true})); }"
            )
            loc.press("Escape")  # cerrar el calendario si se abrió

    # ── tipo de documento en la grilla ─────────────────────────────────────────
    def _fijar_tipo_documento(self, tipo_doc: str):
        """Fija el selector 'Tipo Documento' de la grilla (select#tipoDocRecepcion).

        La grilla tiene su propio selector de tipo, que arranca en Factura (1):
        si no se fija, buscar por CUFE un Documento Equivalente (20) o una Nota
        Crédito (91) devuelve 0 filas aunque el documento exista.
        """
        sel = self.page.locator("select#tipoDocRecepcion").first
        if sel.input_value() != tipo_doc:
            sel.select_option(tipo_doc)
            time.sleep(0.3)

    # ── descarga de PDF ────────────────────────────────────────────────────────
    def descargar_pdf(self, cufe: str, fecha: datetime | None = None,
                      tipo_doc: str = "1") -> bytes:
        """Filtra por CUFE, abre 'Ver PDF' y devuelve los bytes del PDF.

        `fecha` es la fecha del documento: se usa para acotar la grilla a ese
        día antes de buscar por CUFE (si no, la grilla queda en 'hoy' y no
        encuentra documentos de días anteriores). `tipo_doc` debe coincidir con
        el tipo del documento (1=Factura, 91=Nota Crédito, 20=Doc Equivalente).
        """
        ultimo_error: Exception | None = None
        for intento in range(3):
            try:
                return self._descargar_pdf_una_vez(cufe, fecha, tipo_doc)
            except Exception as e:  # noqa: BLE001 — reintentar ante lentitud/modales del portal
                ultimo_error = e
                self._cerrar_modales()
                time.sleep(2)
        raise ultimo_error  # type: ignore[misc]

    def _descargar_pdf_una_vez(self, cufe: str, fecha: datetime | None, tipo_doc: str) -> bytes:
        p = self.page
        self._cerrar_modales()  # limpiar cualquier modal dejado por el doc anterior
        self._fijar_tipo_documento(tipo_doc)
        if fecha is not None:
            self._fijar_rango_fecha(fecha, fecha)
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

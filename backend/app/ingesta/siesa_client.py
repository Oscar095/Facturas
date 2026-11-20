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

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from playwright.sync_api import Page, sync_playwright

log = logging.getLogger("ingesta.siesa")

PDF_URL_FRAGMENT = "pdf-recepcion"

# validarFilters() del portal rechaza rangos de más de 90 días con un popup y NO
# consulta: la grilla se queda con el listado anterior.
MAX_DIAS_RANGO = 90


class CredencialesRechazadas(RuntimeError):
    """El portal rechazó el login (clave errada, cuenta bloqueada, pide 2FA).

    No se reintenta: cada intento con la misma clave acerca la cuenta al bloqueo.
    El 2026-11-19 la cuenta del robot amaneció bloqueada y los 3 reintentos por
    corrida solo sumaban intentos fallidos.
    """


class DocumentoSinPdf(RuntimeError):
    """El portal no tiene representación gráfica (PDF) del documento.

    Pasa cuando el proveedor manda el XML sin el PDF. Es permanente para ese
    documento, así que no se reintenta dentro de la corrida.
    """


class SesionPerdida(RuntimeError):
    """El portal cerró la sesión a mitad de corrida.

    Lo hace tras 10 min sin actividad de mouse/teclado (p. ej. si una llamada a
    la IA o a la BD se demora): abre el popup 'Sesión expirada' y vuelve al
    login. Sin detectarlo, cada documento restante esperaba 30 s por un
    selector que ya no existe. Quien la reciba puede llamar reiniciar_sesion().
    """


# Popups SweetAlert2 del portal. El más dañino es el de verFactura cuando el
# documento no tiene PDF ("¿Desea generar la factura web?", con botones
# 'Generar factura web' y 'Cerrar'): su fondo tapa toda la página, así que cada
# clic posterior en 'Buscar' esperaba 30 s y fallaba. Desde el 2026-10-09 eso
# tumbaba en cascada el resto de facturas y el listado de equivalentes, y las
# notas crédito ni se pedían. Ver el gotcha 14 en CLAUDE.md.
_JS_SWAL_TEXTO = """() => {
  const c = document.querySelector('.swal2-container');
  if (!c) return null;
  const t = c.querySelector('.swal2-title'), h = c.querySelector('.swal2-html-container');
  return [t && t.innerText, h && h.innerText].filter(Boolean).join(' - ').replace(/\\s+/g, ' ').trim();
}"""

# Botones visibles del popup, para decidir cuál pulsar ANTES de pulsar nada.
_JS_SWAL_BOTONES = """() => {
  const c = document.querySelector('.swal2-container');
  if (!c) return null;
  const vis = (sel) => { const b = c.querySelector(sel); return !!(b && b.offsetParent !== null); };
  return {cancelar: vis('button.swal2-cancel'), cerrar: vis('button.swal2-close'),
          confirmar: vis('button.swal2-confirm'), negar: vis('button.swal2-deny')};
}"""

# Índice de la fila de la grilla cuyo documento tiene ese CUFE (-1 si no está).
# Las filas son `ng-repeat="item in $ctrl.document.list"`.
_JS_FILA_DEL_CUFE = """(cufe) => {
  const filas = [...document.querySelectorAll('tr[ng-repeat*="$ctrl.document.list"]')];
  return filas.findIndex(tr => {
    try { const s = window.angular.element(tr).scope(); return !!(s && s.item && s.item.cufe === cufe); }
    catch (e) { return false; }
  });
}"""

_SESION_EXPIRADA = "sesión expirada"   # título del popup del portal (TITULO_SESION_EXPIRADA)

# Red de seguridad si el popup no se deja cerrar con sus botones ni con Escape.
_JS_QUITAR_SWAL = """() => {
  document.querySelectorAll('.swal2-container').forEach(c => c.remove());
  for (const el of [document.body, document.documentElement])
    el.classList.remove('swal2-shown', 'swal2-height-auto', 'swal2-no-backdrop',
                        'swal2-toast-shown', 'swal2-iosfix');
}"""

# Las respuestas de /login/get-token y /login/user-login vienen cifradas; se
# descifran con la misma función del portal. Devuelve null si no se pudo.
_JS_DESCIFRAR_LOGIN = """(cifrado) => {
  try {
    const inj = window.angular && window.angular.element(document.body).injector();
    if (!inj) return null;
    let d = inj.get('LoginService').infoSecurity.desencriptar(cifrado);
    if (typeof d === 'string') d = JSON.parse(d);
    if (!d || typeof d !== 'object') return null;
    return {error: !!d.error, token: !!d.token, mensaje: d.message ? String(d.message) : ''};
  } catch (e) { return null; }
}"""

# Plan B si no se pudo descifrar: ante CUALQUIER rechazo la pantalla de login
# muestra "Usuario o contraseña incorrectos" durante 7 s (no distingue bloqueo).
_JS_ERROR_LOGIN_UI = """() => {
  const el = document.querySelector('#username_f') || document.querySelector("input[type='password']");
  if (!el || !window.angular) return null;
  const s = window.angular.element(el).scope();
  return (s && s.$ctrl && s.$ctrl.errorMessage) ? String(s.$ctrl.errorMessage) : null;
}"""

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
    // tamaño de página por el modelo: el select#regist tiene ng-change que lanza
    // OTRA búsqueda, y sus respuestas cruzadas con la de 'Buscar' corrían la
    // paginación (se leía la página 1 dos veces y nunca la última)
    if (f.registros) ctrl.countRegist = f.registros;
    ctrl.currentPage = 1;
  };
  try { sc.$apply(aplicar); } catch (e) { aplicar(); sc.$applyAsync(); }
  return true;
}"""

# Cambiar de página por el MODELO y no clicando `li.pagination-next`: cuando el
# "siguiente" está deshabilitado, Bootstrap le pone `pointer-events: none` y el
# clic de Playwright espera los 30s completos antes de reventar, tumbando la
# corrida entera (pasó en la ejecución #120).
_JS_IR_PAGINA = "(n) => {" + _JS_CTRL + """
  if (!ctrl || !sc || typeof ctrl.getDocumentsFromSp !== 'function') return false;
  const ir = () => { ctrl.currentPage = n; ctrl.getDocumentsFromSp(); };
  try { sc.$apply(ir); } catch (e) { ir(); sc.$applyAsync(); }
  return true;
}"""

_JS_ESTADO = "() => {" + _JS_CTRL + """
  if (!ctrl) return null;
  return {
    cargando: !!ctrl.loading,
    pagina: Number(ctrl.currentPage) || 1,
    paginas: Number(ctrl.totalPages) || 1,
    total: Number(ctrl.totalItems) || 0,
    // si la consulta al SP falla, el portal deja document = {list: [], error: true}
    // sin avisar nada: leído a secas parecía "no hay documentos"
    error: !!(ctrl.document && ctrl.document.error),
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


def _primera_linea(e: BaseException) -> str:
    """Primera línea de un error (los de Playwright traen un 'Call log' largo)."""
    lineas = str(e).strip().splitlines()
    return lineas[0] if lineas else type(e).__name__


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
        self.ultimo_total: int = 0   # total que reportó el portal en el último listado

    # ── ciclo de vida ────────────────────────────────────────────────────────
    def __enter__(self) -> "SiesaClient":
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
            self._nuevo_contexto()
            self._login()
            return self
        except Exception:
            # Si __enter__ falla, Python NO llama a __exit__: hay que cerrar aquí
            # o la sesión de Playwright queda viva y deja el hilo con un loop de
            # asyncio corriendo. La SIGUIENTE corrida que caiga en ese mismo hilo
            # del threadpool revienta al instante con "Playwright Sync API inside
            # the asyncio loop" — un fallo de login envenenaba las corridas
            # posteriores (pasó: ejecución #121 tumbó a la #122).
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *exc):
        # Nunca debe lanzar: taparía el error real que provocó la salida.
        try:
            if self._browser:
                self._browser.close()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._browser = self._context = self.page = None
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None

    def _nuevo_contexto(self):
        """Contexto de navegador limpio (sin cookies ni localStorage de antes)."""
        if self._context is not None:
            try:
                self._context.close()
            except Exception:  # noqa: BLE001 — ya cerrado o el navegador cayó
                pass
        self._context = self._browser.new_context(locale="es-CO", accept_downloads=True)
        self.page = self._context.new_page()

    def reiniciar_sesion(self):
        """Vuelve a entrar al portal desde cero (tras una SesionPerdida)."""
        self._nuevo_contexto()
        self._login()

    # ── login ────────────────────────────────────────────────────────────────
    def _login(self, intentos: int = 3):
        """Inicia sesión, reintentando si el portal no alcanza a pintar el formulario.

        El portal a veces tarda o responde una página vacía y el `fill` del
        usuario se cae con `Timeout ... waiting for locator(input...)`. No es un
        bloqueo: al reintentar entra. Sin reintento, una lentitud puntual deja
        al robot sin correr hasta la siguiente franja horaria.

        Lo que NO se reintenta es un rechazo del portal (CredencialesRechazadas):
        repetir la misma clave solo suma intentos fallidos hacia el bloqueo.
        Cada reintento arranca en un contexto LIMPIO: si el intento anterior sí
        alcanzó a entrar, la sesión quedaba en localStorage, el portal ya no
        mostraba el formulario y el robot tecleaba el usuario en otro campo.
        """
        ultimo: Exception | None = None
        for intento in range(1, intentos + 1):
            try:
                if intento > 1:
                    self._nuevo_contexto()
                self._login_una_vez()
                return
            except CredencialesRechazadas:
                raise
            except Exception as e:  # noqa: BLE001
                ultimo = e
                if intento < intentos:
                    time.sleep(5 * intento)
        raise ultimo  # type: ignore[misc]

    def _campo_login(self, id_v31: str, alternativos: str):
        """Campo del formulario de login. En v3.1.0.19 se buscan por id: con la
        lista de selectores viejos, `.first` toma el primero en orden del DOM, y
        hubo días en que ese era el `input#firstName` OCULTO del formulario de
        registro — el `fill` esperaba 30 s y la corrida moría (#341-#346)."""
        campo = self.page.locator(id_v31)
        return campo if campo.count() else self.page.locator(alternativos)

    def _login_una_vez(self):
        p = self.page
        p.goto(self.url, wait_until="networkidle", timeout=60000)
        time.sleep(2)
        self._campo_login(
            "#username_f",
            "input[type='email']:visible, input[type='text']:visible, "
            "input[name*='user' i]:visible, input[placeholder*='usuario' i]:visible, "
            "input[placeholder*='correo' i]:visible",
        ).first.fill(self.usuario)
        self._campo_login("#pass_f", "input[type='password']:visible").first.fill(self.clave)

        respuestas: dict = {}

        def capturar(r):
            if r.request.method == "POST":
                for nombre in ("get-token", "user-login"):
                    if r.url.endswith("/login/" + nombre):
                        respuestas[nombre] = r

        p.on("response", capturar)
        try:
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
            # es que aparezca el botón Buscar de los filtros de búsqueda. Mientras se
            # espera se revisa si el portal RECHAZÓ el login, para no quemar 45 s ni
            # reintentar una clave que no sirve.
            buscar = p.locator("button:has-text('Buscar')").first
            vistas: dict = {}
            limite = time.time() + 45
            while not buscar.is_visible():
                rechazo = self._rechazo_de_login(respuestas, vistas)
                if rechazo:
                    raise CredencialesRechazadas(
                        f"El portal rechazó el login: {rechazo}. No se reintenta para no "
                        "bloquear la cuenta; revisar USERNAME_FACTURAS/PASSWORD_FACTURAS "
                        "(.env local y App Settings de Azure)."
                    )
                if time.time() > limite:
                    raise TimeoutError(
                        "Tras el login no apareció el botón 'Buscar' de la pantalla de "
                        "recepción en 45 s"
                    )
                time.sleep(0.5)
        finally:
            p.remove_listener("response", capturar)
        p.wait_for_load_state("networkidle", timeout=45000)
        time.sleep(2)

    def _rechazo_de_login(self, respuestas: dict, vistas: dict) -> str | None:
        """Motivo por el que el portal rechazó el login, o None si no lo rechazó (aún).

        Lee las respuestas cifradas de get-token/user-login con la función del
        propio portal: así se distingue una cuenta bloqueada ("Su cuenta se
        encuentra bloqueada…") de una clave errada, cosa que la pantalla no hace.
        Si no se pudieran descifrar (cambio del portal), cae al mensaje de la UI.
        """
        # copia: el listener `capturar` puede agregar 'user-login' MIENTRAS se
        # descifra 'get-token' (Playwright entrega eventos dentro de cualquier
        # llamada), y mutar el dict durante el for lanzaba RuntimeError
        for nombre, resp in list(respuestas.items()):
            if nombre in vistas:
                continue
            try:
                vistas[nombre] = self.page.evaluate(_JS_DESCIFRAR_LOGIN, resp.text())
            except Exception:  # noqa: BLE001 — sin cuerpo legible: se usa el plan B
                vistas[nombre] = None
        for nombre in ("get-token", "user-login"):
            d = vistas.get(nombre)
            if not d:
                continue
            if d["error"]:
                return d["mensaje"] or "error sin mensaje"
            if nombre == "get-token" and d["token"]:
                return ("el portal pidió el token de doble autenticación (2FA), "
                        "que el robot no puede completar")
        try:
            return self.page.evaluate(_JS_ERROR_LOGIN_UI)
        except Exception:  # noqa: BLE001 — la página pudo cambiar de estado (login exitoso)
            return None

    # ── estado del listado (leído del scope de Angular) ───────────────────────
    def _estado_listado(self) -> dict | None:
        """Filas ya descifradas + paginación, directo del controlador Angular."""
        return self.page.evaluate(_JS_ESTADO)

    def _esperar_listado(self, pagina: int = 1, timeout: float = 130.0) -> dict:
        # 130 s: el propio portal le da 120 s al SP (timeoutSeconds) antes de rendirse
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
        # Antes se devolvía `ultimo` igual: mientras carga, document.list sigue
        # siendo el de la búsqueda ANTERIOR (otro tipo, o la página previa), y se
        # leía como si fuera el resultado de esta.
        raise RuntimeError(f"El listado del portal no terminó de cargar en {timeout:.0f} s "
                           f"(página {pagina})")

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

        tipo_doc: 1=Factura, 91=Nota Crédito, 92=Nota Débito, 20=Doc Equivalente,
        94=Nota a Doc Equivalente.

        Se maneja la UI y se leen las filas del scope de Angular: el endpoint
        del listado va cifrado y no se puede llamar por HTTP (ver el docstring
        del módulo).
        """
        p = self.page
        desde, hasta = datetime.fromisoformat(fecha_desde), datetime.fromisoformat(fecha_hasta)
        if (hasta - desde).days > MAX_DIAS_RANGO:
            raise ValueError(
                f"El portal solo acepta rangos de hasta {MAX_DIAS_RANGO} días "
                f"(se pidió {fecha_desde}..{fecha_hasta}); partir la consulta"
            )
        self._cerrar_modales()
        self._fijar_tipo_documento(tipo_doc)
        # el CUFE se limpia aquí mismo: si quedó del PDF anterior, el listado
        # devolvería una sola fila
        if not self._fijar_rango_fecha(desde, hasta, tipo_doc=tipo_doc, cufe="",
                                       registros="100"):
            self._fijar_tamano_pagina()  # sin acceso al modelo: por el select

        p.locator("button:has-text('Buscar')").first.click()
        estado = self._esperar_listado(pagina=1)
        self._validar_busqueda(estado)

        docs: list[DocumentoPortal] = []
        vistos: set[str] = set()

        def agregar(filas: list, pagina: int):
            nuevas = [self._mapear(r) for r in filas]
            claves = [d.cufe or d.id_portal for d in nuevas]
            if nuevas and all(c in vistos for c in claves):
                # una respuesta atrasada repintó una página ya leída: seguir
                # sería saltarse la página que de verdad se pidió
                raise RuntimeError(f"El portal devolvió repetida la página {pagina} del listado")
            for d, c in zip(nuevas, claves):
                if c not in vistos:
                    vistos.add(c)
                    docs.append(d)

        agregar(estado["filas"], 1)
        paginas = max(1, estado["paginas"])
        for pagina in range(2, paginas + 1):
            if not p.evaluate(_JS_IR_PAGINA, pagina):
                # sin acceso al controlador: se intenta el clic, con timeout
                # corto para no quemar 30s si el botón está deshabilitado
                siguiente = p.locator("li.pagination-next a").first
                if not siguiente.count():
                    break
                try:
                    siguiente.click(timeout=5000)
                except Exception:  # noqa: BLE001 — sin "siguiente" utilizable, se acabó
                    break
            estado = self._esperar_listado(pagina=pagina)
            self._validar_busqueda(estado)
            agregar(estado["filas"], pagina)
        # sincronizar lo compara con len(docs): un listado incompleto cuenta como error
        self.ultimo_total = estado["total"]
        if len(docs) < self.ultimo_total:
            log.warning("Tipo %s: se leyeron %d documentos de %d que reporta el portal",
                        tipo_doc, len(docs), self.ultimo_total)
        return docs

    def _validar_busqueda(self, estado: dict):
        """Falla en voz alta si el portal no hizo la búsqueda o esta falló.

        Sin esto se leía como "no hay documentos" (o como el listado ANTERIOR):
        si los filtros no pasan validarFilters() el portal abre un popup y no
        consulta, y si el SP falla deja la lista vacía con `error: true`.
        """
        aviso = self._cerrar_popup_swal()
        if aviso is not None:
            raise RuntimeError(f"El portal no hizo la búsqueda: {aviso}")
        if estado.get("error"):
            raise RuntimeError("La consulta del listado falló en el portal (error del SP)")

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
    def _cerrar_popup_swal(self) -> str | None:
        """Cierra el popup SweetAlert2 abierto y devuelve su texto (None si no hay).

        El botón se elige ANTES de pulsar: 'Cerrar' (swal2-cancel) si existe —en
        el popup de documento sin PDF el de confirmar es 'Generar factura web',
        que abriría otra pestaña—, si no la X, y confirmar solo cuando es el
        ÚNICO botón ('Enterado!'). Si ese clic falla NO se prueba otro botón
        (podría disparar una acción): se pasa a Escape y, si nada, se quita del DOM.

        Si el popup es 'Sesión expirada' lanza SesionPerdida: el portal ya cerró
        la sesión y nada más en esta página puede funcionar.
        """
        p = self.page
        aviso = p.evaluate(_JS_SWAL_TEXTO)
        if aviso is None:
            return None
        botones = p.evaluate(_JS_SWAL_BOTONES) or {}
        if botones.get("cancelar"):
            sel = "button.swal2-cancel"
        elif botones.get("cerrar"):
            sel = "button.swal2-close"
        elif botones.get("confirmar") and not botones.get("negar"):
            sel = "button.swal2-confirm"
        else:
            sel = None
        pulsado = False
        if sel:
            try:
                p.locator(f".swal2-container {sel}").first.click(timeout=2000)
                pulsado = True
            except Exception:  # noqa: BLE001
                pass
        if not pulsado:
            try:
                p.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
        try:
            p.locator(".swal2-container").first.wait_for(state="detached", timeout=3000)
        except Exception:  # noqa: BLE001 — no se fue: se quita del DOM
            p.evaluate(_JS_QUITAR_SWAL)
        aviso = aviso or "(popup sin texto)"
        if _SESION_EXPIRADA in aviso.lower():
            raise SesionPerdida(f"El portal cerró la sesión: {aviso}")
        return aviso

    def _cerrar_pestanas_extra(self):
        """Cierra las pestañas que abre el portal. verFactura hace window.open()
        del PDF en cada descarga: sin cerrarlas, una corrida larga acumulaba una
        pestaña con un PDF por documento dentro del mismo Chromium."""
        if self._context is None:
            return
        for pagina in list(self._context.pages):
            if pagina is not self.page:
                try:
                    pagina.close()
                except Exception:  # noqa: BLE001 — ya cerrada
                    pass

    def _esperar_y_cerrar_popup(self, timeout: float = 3.0) -> str | None:
        """Espera a que aparezca un popup SweetAlert2 (el portal lo abre un instante
        después de la respuesta que lo provoca) y lo cierra; devuelve su texto."""
        limite = time.time() + timeout
        while True:
            aviso = self._cerrar_popup_swal()
            if aviso is not None or time.time() > limite:
                return aviso
            time.sleep(0.2)

    def _cerrar_modales(self):
        """Cierra cualquier popup o modal abierto y elimina backdrops residuales.

        El portal muestra modales (validación de documento, visor de PDF) y
        popups SweetAlert2 (documento sin PDF, validaciones) que, si quedan
        abiertos, tapan el botón 'Buscar' del siguiente documento y hacen fallar
        toda la corrida en cascada. Se cierra defensivamente antes de cada
        descarga y de cada listado.
        """
        p = self.page
        # la pestaña del PDF anterior se abre un instante DESPUÉS de su respuesta,
        # así que también se barre aquí, antes de cada descarga y listado
        self._cerrar_pestanas_extra()
        aviso = self._cerrar_popup_swal()
        if aviso is not None:
            log.warning("Se cerró un popup del portal que había quedado abierto: %s", aviso)
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
                           tipo_doc: str | None = None, cufe: str = "",
                           registros: str | None = None) -> bool:
        """Fija el rango de fechas (y opcionalmente tipo/CUFE/tamaño de página).

        Se escribe el MODELO de Angular, no el input: el campo es de texto con
        datepicker propio y lo tecleado se pierde, así que la grilla se quedaba
        en 'hoy' — se veían 8 documentos donde había 102. Si el modelo no está
        accesible se cae al método viejo (teclear + eventos input/change) y
        devuelve False (el tamaño de página entonces no quedó fijado).
        """
        ok = self.page.evaluate(_JS_FIJAR_FILTROS, {
            "desde": desde.strftime("%Y-%m-%dT00:00:00"),
            "hasta": hasta.strftime("%Y-%m-%dT23:59:59"),
            "tipo_doc": tipo_doc,
            "cufe": cufe,
            "registros": registros,
        })
        if ok:
            return True

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
        return False

    # ── tipo de documento en la grilla ─────────────────────────────────────────
    def _fijar_tipo_documento(self, tipo_doc: str):
        """Fija el selector 'Tipo Documento' de la grilla (select#tipoDocRecepcion).

        La grilla tiene su propio selector de tipo, que arranca en Factura (1):
        si no se fija, buscar por CUFE un Documento Equivalente (20) o una Nota
        Crédito (91) devuelve 0 filas aunque el documento exista.
        """
        sel = self.page.locator("select#tipoDocRecepcion").first
        if not sel.count():
            # Sin la pantalla de recepción no hay nada que hacer en esta página.
            # Antes cada documento restante esperaba aquí 30 s, uno tras otro.
            raise SesionPerdida("La pantalla de recepción ya no está (¿se cerró la sesión del portal?)")
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
        errores: list[Exception] = []
        for intento in range(3):
            try:
                return self._descargar_pdf_una_vez(cufe, fecha, tipo_doc)
            except (DocumentoSinPdf, SesionPerdida):
                raise  # reintentar en esta misma página no lo cambia
            except Exception as e:  # noqa: BLE001 — reintentar ante lentitud/modales del portal
                errores.append(e)
                self._cerrar_modales()
                time.sleep(2)
        # El PRIMER error suele ser la causa; los reintentos fallan a veces por
        # consecuencia de él. Antes solo quedaba el último y la causa se perdía.
        primero, ultimo = _primera_linea(errores[0]), _primera_linea(errores[-1])
        if primero == ultimo:
            raise errores[-1]
        raise RuntimeError(f"{primero} (y al reintentar: {ultimo})") from errores[-1]

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
        # Se espera a que la búsqueda TERMINE y se abre la fila de ESTE CUFE.
        # Antes: un networkidle (que en esta SPA vuelve al instante) + 2 s fijos,
        # y se abría la PRIMERA fila sin mirarla — una respuesta atrasada de una
        # búsqueda anterior podía dejar en pantalla otro documento, y su PDF se
        # guardaba con el CUFE equivocado.
        self._validar_busqueda(self._esperar_listado(pagina=1, timeout=60))
        indice = p.evaluate(_JS_FILA_DEL_CUFE, cufe)
        if indice < 0:
            raise RuntimeError(f"El portal no devolvió la fila del CUFE {cufe[:16]}…")
        fila = p.locator('tr[ng-repeat*="$ctrl.document.list"]').nth(indice)
        fila.locator("button.btn-default-drop").click()
        time.sleep(0.5)

        # La respuesta se ata a la petición que dispara ESTE clic: una respuesta
        # atrasada de un intento o documento anterior (el XHR sigue vivo tras
        # nuestro timeout) no puede tomarse por la de este documento.
        pedidas: list = []

        def al_pedir(rq):
            if PDF_URL_FRAGMENT in rq.url and rq.method == "POST":
                pedidas.append(rq)

        p.on("request", al_pedir)
        try:
            with p.expect_response(lambda r: r.request in pedidas, timeout=45000) as resp_info:
                fila.locator("a:has-text('Ver PDF')").click()
            resp = resp_info.value
        finally:
            p.remove_listener("request", al_pedir)
        body = resp.body()
        if body[:4] == b"%PDF":
            self._cerrar_pestanas_extra()
            caja_cufe.fill("")  # limpiar el filtro para la siguiente descarga
            return body

        # No llegó un PDF: verFactura abre su popup (o el de 'Sesión expirada',
        # que lanza SesionPerdida al cerrarse). Solo es "sin PDF" la respuesta 200
        # que el portal mismo interpreta así ('-1' cifrado en text/plain, ~44
        # bytes). Cualquier otra (4xx, 5xx, otro formato) es un error que se
        # reintenta y CUENTA como error: tomarla por "sin PDF" la callaba.
        aviso = self._esperar_y_cerrar_popup()
        tipo = resp.headers.get("content-type", "")
        sin_pdf = "representación gráfica" in (aviso or "").lower() or (
            not aviso and "text/plain" in tipo and len(body) < 200)
        if resp.status == 200 and sin_pdf:
            raise DocumentoSinPdf(aviso or "El portal no tiene el PDF de este documento")
        raise RuntimeError(f"pdf-recepcion respondió HTTP {resp.status} ({tipo or 'sin tipo'}, "
                           f"{len(body)} bytes)" + (f": {aviso}" if aviso else ""))

    # ── util ───────────────────────────────────────────────────────────────────
    def _url_api(self, path: str) -> str:
        # https://portalfe.siesacloud.com/PortalPTBack/frontend/web/index.php/<path>
        return f"https://portalfe.siesacloud.com/PortalPTBack/frontend/web/index.php/{path}"

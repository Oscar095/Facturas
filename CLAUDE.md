# CLAUDE.md

Guía para trabajar este repo en sesiones de Claude Code. Complementa al `README.md`
(que es para humanos/instalación); aquí va lo **no obvio**: cómo correr las cosas en
este entorno, las decisiones tomadas y los "gotchas" que ya costaron depuración.

## Qué es

Portal de recepción de facturas electrónicas. Automatiza la descarga diaria del portal
**Siesa Smart4B**, guarda los PDF en **Azure Blob (Data Lake `datalakekos`, contenedor
`facturas`)** y los metadatos en **Azure SQL**, y expone un portal web (React + FastAPI)
para revisar estado, asignar áreas responsables y cargar los documentos que faltan para
contabilizar. n8n dispara la ingesta a diario por HTTP.

Flujo: `n8n → POST /api/jobs/sync → ingesta Playwright (portal Siesa) → Blob + SQL`.
La ingesta trae 3 tipos de documento en la misma sesión de navegador
(`filters[tipoDocRecepcion]`): **Facturas** (`tipo_doc=1`) y **Documentos Equivalentes**
(`tipo_doc=20`) van a la tabla `facturas` diferenciados por la columna
`tipo_documento` (`FACTURA|EQUIVALENTE`) — un Equivalente reemplaza funcionalmente a la FV,
mismo flujo de área/completitud/aprobación. Las **Notas Crédito** (`tipo_doc=91`) van a la
tabla aparte `notas_credito` (solo consulta: sin área ni flujo de aprobación; endpoint
`/api/notas-credito` protegido con permiso `ver_todas_areas`; blobs en
`notas_credito/AAAA/MM/`). No se extraen Notas Débito (`92`) — no se ha pedido.

## Entorno de ejecución (IMPORTANTE)

- Windows. Hay **PowerShell** y **Bash** disponibles. La ruta primaria es `c:\Users\oscaro\Facturas`.
- **El intérprete con todo instalado es `.venv/Scripts/python.exe`** (Playwright, pyodbc,
  azure-storage-blob viven ahí). El `python` del PATH del sistema **no** tiene las dependencias.
  Siempre usa `.venv/Scripts/python.exe` para correr scripts.
- **Los scripts de `scripts/` se ejecutan desde la raíz del repo** (hacen
  `sys.path.insert(0, "backend")` para importar `app.*`). Ejemplo:
  ```bash
  .venv/Scripts/python.exe scripts/<script>.py
  ```
- **El backend se corre desde `backend/`**:
  ```bash
  cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```
  Se levanta **sin `--reload`**: si cambias código del backend hay que **reiniciar el proceso**
  para que tome los cambios (matar el uvicorn y volver a arrancar).
- Con `BD_HOST` vacío en `.env`, el backend cae a **SQLite local** (`facturas_dev.db`) y guarda
  archivos en `descargas/blob/`. Hoy `.env` apunta a **Azure SQL de producción** (ver abajo).

## Base de datos y almacenamiento

- La BD es `kx_ecommerce` en `myappskos.database.windows.net` — es la **BD de producción de
  e-commerce del usuario**. Todas las tablas de esta app viven **aisladas en el esquema
  `facturas`** (decisión explícita). Nunca crear tablas fuera de ese esquema.
  `crear_esquema_si_falta()` lo crea si no existe; `Base` usa `MetaData(schema="facturas")`.
- Blob: cuenta `datalakekos`, contenedor `facturas`. Rutas: `facturas/AAAA/MM/{nit}_{folio}.ext`.

## Gotchas de la ingesta Siesa (`backend/app/ingesta/siesa_client.py`)

Esto es lo más frágil del proyecto. Ya resuelto, pero entiéndelo antes de tocarlo:

1. **El PDF NO se puede bajar por HTTP directo.** El request `pdf-recepcion` va con
   `x-payload-encryption: true` y cuerpo **cifrado en el navegador** por Angular. Por eso el
   PDF se obtiene **por la UI** (clic en "Ver PDF") interceptando la respuesta
   `application/pdf`. El **listado sí** es HTTP directo (`pst/listado/recepcion-proveedores`,
   paginado reusando la sesión del navegador con `page.request.post`).
2. **El campo "Fecha Desde" se reinicia solo a HOY.** El datepicker de Angular ignora un
   `.fill()` simple. Si no se fija bien el rango, la grilla solo muestra documentos del día
   actual y **buscar por CUFE un documento de días anteriores devuelve 0 filas**. Solución:
   `_fijar_rango_fecha()` escribe con eventos `input`/`change`, y `descargar_pdf(cufe, fecha)`
   acota la grilla **al día del documento** antes de buscar por CUFE.
3. **La grilla tiene su PROPIO selector de tipo de documento** (`select#tipoDocRecepcion`,
   arranca en Factura). El listado por HTTP filtra por tipo vía parámetro, pero la
   descarga de PDF va por la UI: si no se fija el selector al tipo del documento
   (`_fijar_tipo_documento`), buscar por CUFE un Equivalente (20) o una Nota Crédito (91)
   devuelve 0 filas aunque exista. `descargar_pdf(cufe, fecha, tipo_doc=...)` lo hace.
4. **Modales atascados tumban la corrida en cascada.** Si un PDF tarda y queda un modal
   abierto, su backdrop tapa el botón "Buscar" del siguiente documento y fallan todos.
   `_cerrar_modales()` se llama antes de cada descarga (cierre amable + red de seguridad por JS
   que oculta modales/backdrops residuales). `descargar_pdf` además **reintenta hasta 3 veces**.
5. La sincronización es **idempotente**: dedup por CUFE (`_existe_cufe`). Reejecutar el mismo
   rango no duplica nada. Un fallo por-documento hace `rollback` de esa factura y **continúa**
   con las demás (no aborta la corrida).

Para probar la ingesta real (escribe en Azure SQL + Blob; es idempotente):
```bash
.venv/Scripts/python.exe scripts/probar_ingesta.py 5   # limita a 5 nuevas
```

## Convenciones del backend

- **Auth de usuarios**: JWT (PyJWT) + hash **PBKDF2-HMAC-SHA256** (no passlib/bcrypt — se
  eligió por compatibilidad con Python 3.14). Ver `security.py`.
- **`/api/jobs/*`** (los llama n8n) van por header **`x-api-key`** (= `JOBS_API_KEY`),
  separado del JWT del portal. Endpoint de disparo: `POST /api/jobs/sync?dias=3&esperar=true`.
- **Descarga de archivos**: los endpoints (`/api/facturas/{id}/pdf`,
  `/api/facturas/documento/{id}/archivo`) **sirven los bytes desde el backend** (proxy), NO
  redirigen a una URL SAS de Azure Blob. Motivo: el frontend usa `fetch()` con el token JWT y
  una redirección cross-origin a `blob.core.windows.net` la bloquea CORS (Blob no tiene CORS).
  **No reintroducir el patrón de redirect/SAS.**
- **SQL Server + UNIQUE con NULL**: SQL Server trata múltiples `NULL` como duplicados en un
  UNIQUE constraint (a diferencia de ANSI/Postgres). Para columnas nullable únicas se usa un
  **índice único filtrado**: `Index(..., unique=True, mssql_where=text("col IS NOT NULL"))`.
  Ver `ReglaArea` y `Factura.cufe` en `models.py` (el de `facturas.cufe` se migró con
  `scripts/migrar_carga_manual.py` porque las facturas manuales pueden venir sin CUFE).
- **SPA**: `main.py` sirve `index.html` con `Cache-Control: no-cache` para evitar que el
  navegador cachee un `index.html` viejo que referencia bundles de Vite ya borrados.

## Reglas de negocio

- **Máquina de estados de la factura**: `nueva → asignada → docs_pendientes →
  lista_contabilizar (auto) → procesada (botón Procesar) → aprobada (botón Aprobar) →
  contabilizada (rol contabilidad/admin)`.
- **Completitud** (`services/reglas.py`): siempre FV (el PDF descargado cuenta como FV). Si la
  orden es **OCN** se exige OCN **+ CRN**; si es **OCS**, solo OCS. Al cumplirse pasa a
  `lista_contabilizar` automáticamente.
- **Procesar** (`POST /api/facturas/{id}/procesar`): paso HUMANO — el responsable declara que
  los documentos son suficientes, **aunque haya faltantes según las reglas** (hay facturas que
  no requieren todos los documentos); requiere área asignada. **Aprobar**
  (`POST /{id}/aprobar`, body `{firma_id}`): solo desde `procesada`; re-verifica que la firma
  sea del usuario (404 si no) y **estampa la firma en TODOS los documentos PDF adjuntos,
  sin importar su tipo** (los no-PDF se omiten y queda anotado en el evento) — en TODAS
  las páginas, abajo a la derecha, con texto
  "Aprobado por … — fecha" (`services/firmar_pdf.py`, pypdf+reportlab). El sellado se sube como blob nuevo
  `*_firmado.pdf` (el original queda en el Blob por trazabilidad) y se actualizan
  `documento.blob_path` y `factura.blob_pdf` (la FV comparte ruta). Documentos no-PDF se
  omiten y queda anotado en el evento. **Contabilizar** exige `aprobada`.
  `evaluar_completitud` NUNCA degrada los estados manuales
  (`procesada`/`aprobada`/`contabilizada`). Todo queda auditado en `eventos`.
- **OCN/OCS/CRN los sube el usuario** desde el portal — **nunca** se extraen del portal Siesa.
- **Asignación de área** (`asignar_area`, cascada de más barata a más cara):
  1. NIT con una sola área en `reglas_area` → directo.
  2. Varias áreas → patrones de ítem (normalizados: minúsculas/sin tildes, `normalizar()`)
     contra el **texto del PDF** (`facturas.texto_pdf`, extraído con pypdf en la ingesta —
     gratis, sin IA). Regla sin patrón = área por defecto del proveedor. Si varias áreas
     coinciden (conflicto) no se decide.
  3. **IA (Claude Haiku, `services/ia_area.py`) como ÚLTIMA opción** — solo si `usar_ia` y hay
     key (`API_KEY_IA_CLAUDE` en `.env`). Queda auditada como evento `ia_area`. No gastar
     créditos: nunca ampliar su uso sin que el usuario lo pida.
  4. Nada decide → **sin asignar** (nunca adivinar); dropdown manual en el detalle.
  Las reglas se administran desde el portal (Admin → Áreas y reglas: crear/editar/eliminar/
  filtrar) y hay `POST /api/areas/reglas/reaplicar?usar_ia=false` para reaplicarlas a las
  facturas sin área (no toca las ya asignadas; con IA solo si se pasa `usar_ia=true`).
- **Roles y permisos** (`security.py`, `routers/roles.py`, tabla `roles`): los roles son
  **dinámicos**, no hardcoded — se administran desde Portal → Admin → Roles. Cada rol tiene 5
  permisos booleanos: `ver_todas_areas`, `editar_facturas`, `aprobar`, `contabilizar`,
  `administrar`. Los 3 roles "de sistema" (`admin`, `contabilidad`, `area`) se siembran en cada
  arranque (`_sembrar_roles()` en `main.py`, idempotente) con `es_sistema=True` y no se pueden
  editar/eliminar (ni si están en uso). `Usuario.rol` sigue siendo un **string libre sin FK** a
  `roles` (deliberado: evita un ALTER sobre la tabla `usuarios` de producción) — la integridad
  se valida solo en la capa de aplicación (`_validar_rol()` en `routers/usuarios.py`). Los
  endpoints se protegen con `requiere_permiso(...)` / `tiene_permiso(db, usuario, ...)`, no
  comparando el nombre del rol; si un rol no tiene fila en `roles` cae al fallback hardcoded
  `PERMISOS_LEGADO` (replica el comportamiento histórico de los 3 roles originales). El
  frontend recibe los permisos del usuario en `GET /api/auth/yo` (campo `permisos`) y los usa
  con `tienePermiso()` (`util.js`) para mostrar/ocultar UI — **no** volver a chequear
  `usuario.rol === "admin"` directamente en componentes nuevos.
- **Firmas digitales** (`/api/firmas`, página "Mis Firmas"): imágenes que cada usuario sube
  para el futuro flujo de firmar aprobaciones. **Invariante de privacidad: una firma solo la
  ve/usa su dueño — SIN excepción para admin.** Toda consulta filtra por `usuario_id` y una
  firma ajena responde 404 (no 403, para no revelar existencia). Al eliminar se borra también
  el blob (`eliminar()` en blob_storage). No romper esto al construir el flujo de firmado:
  verificar propiedad de `firma_id` otra vez en el momento de firmar.

## Carga manual de facturas (`/cargar-factura`, `routers/carga_facturas.py`)

- Para el ~20% de facturas que NO llegan por Siesa (físicas o de correo). Flujo en 2 pasos,
  **el backend no guarda nada entre uno y otro** (el PDF viaja en ambos requests):
  `POST /api/facturas/carga/extraer` (solo lee el PDF con IA y devuelve los campos) →
  el usuario **revisa/corrige en el formulario** → `POST /api/facturas/carga` (crea la
  factura). La IA **nunca escribe directo en la BD** — extracción ≠ guardado, a propósito.
- La extracción (`services/extraer_factura.py`) usa **Haiku** y manda **solo el texto** del
  PDF (pypdf, gratis) cuando hay capa de texto; el PDF completo como documento (visión, más
  caro) solo si viene escaneado (<150 chars de texto). Es la ÚNICA otra llamada a la API de
  Claude además de `ia_area.py`, y solo corre cuando el usuario pulsa "Extraer datos con IA".
  Si la IA falla, el endpoint devuelve el formulario vacío con advertencia (no 500) y el
  usuario llena a mano — la carga manual nunca depende de la IA.
- La factura creada entra al **mismo flujo que las del portal**: proveedor upsert, blob en
  `facturas/AAAA/MM/`, documento FV, `texto_pdf`, reglas de área y completitud. Se marca con
  `facturas.origen = 'manual'` (vs `'portal'`; visible en el detalle) y evento `carga_manual`.
- Dedup: por CUFE si el usuario lo diligenció, y por (proveedor, número) → 409. El CUFE es
  opcional: por eso `facturas.cufe` pasó a índice único filtrado (ver Convenciones).
- Permiso: `editar_facturas` (endpoint y visibilidad del link/página).

## Listado de facturas

- `GET /api/facturas` filtra por `fecha_desde`/`fecha_hasta` sobre **`fecha_emision`** (no
  `fecha_recepcion`): la emisión se guarda tal cual la entrega el portal (hora local de
  Colombia), así que se compara directo. NO "corregir" esto a `fecha_recepcion` sin aplicar
  el desfase de Bogotá (esa columna sí está en UTC — ver gotcha del Dashboard).

## Dashboard (`/`, página de inicio)

- `GET /api/panel/dashboard?periodo=mes|trimestre|anio|todo` (`routers/panel.py`) alimenta
  `frontend/src/pages/Dashboard.jsx`: KPIs del mes, compras por área (con "Sin asignar"
  destacado) y las facturas con más tiempo sin procesar.
- **Gotcha de zona horaria**: las fechas se guardan en UTC-naive pero el negocio opera en
  Bogotá (UTC-5, sin DST). Los cortes de mes/año se calculan en hora local y se convierten a
  UTC (`_DESFASE_BOGOTA = timedelta(hours=5)`) antes de filtrar. Si se agregan más cortes de
  fecha al panel, seguir ese mismo patrón — comparar directo en UTC sin el desfase corta el
  mes en el momento equivocado.
- El alcance por rol (`area` solo ve lo suyo) se resuelve con `tiene_permiso(db, usuario,
  "ver_todas_areas")`, igual que en `facturas.py` — no repetir el chequeo viejo
  `usuario.rol == "area"`.

## Secretos (NO commitear, NO imprimir)

- Todo lo sensible vive en **`.env`** (gitignored desde el primer commit): credenciales del
  portal Siesa, connection string del Data Lake, credenciales de Azure SQL, `JWT_SECRET`,
  `JOBS_API_KEY`. En la nube van como **App Settings** del App Service.
- No pegar valores de secretos en código, commits, ni en archivos versionados (incluido este).

## Estado / pendientes

- **BLOQUEANTE — login Siesa roto (desde 2026-07-30)**: el portal se actualizó a
  "Siesa E - Invoicing **Versión 3.1.0.17**" y rechaza las credenciales guardadas — el propio
  portal responde "Usuario o contraseña incorrectos". Por eso toda corrida de sync falla con
  `Fallo general: Timeout 45000ms exceeded ... waiting for navigation to '**/documentRecepcion/**'`
  (el login nunca completa; afecta local Y la nube/n8n, que usan la misma clave).
  **Pendiente del usuario**: restablecer la contraseña en el portal y actualizar
  `PASSWORD_FACTURAS` en `.env` + App Settings del App Service. Al tener clave válida,
  re-verificar el robot con `scripts/diagnosticar_login.py` (sin commitear, herramienta local):
  el form nuevo usa `#username_f`/`#pass_f`, el botón de login **NO es `type=submit`**
  (llama `$ctrl.getToken()` → POST `login/get-token`; en diagnóstico funcionó el clic por texto
  "Iniciar Sesión") — puede requerir ajustar `_login()` en `siesa_client.py`. Además hay un
  `#token_input` oculto + botón "VALIDAR TOKEN" (`$ctrl.validarToken()`): posible 2FA que solo
  se puede evaluar con credenciales válidas.
- **Scripts locales sin versionar** (herramientas de diagnóstico, misma máquina):
  `scripts/diagnosticar_login.py` (reproduce el login con screenshots/toasts/errores HTTP) y
  `scripts/ver_ultimo_log.py` (últimas 4 filas de `ejecuciones` con desglose de contadores).
- **Reglas de área**: importadas 184 filas desde el Excel histórico (cruce de NIT por mayoría).
  Quedan ~34 proveedores con NIT ambiguo y ~9 sin NIT (en `reglas_area` con `proveedor_nit`
  NULL) y 17 con múltiples áreas candidatas — se completan a mano o cuando exista extracción IA.
- **Texto de facturas**: `facturas.texto_pdf` se llena en la ingesta (pypdf) y fue
  backfilleado para todas las facturas históricas (`scripts/migrar_texto_pdf.py`, idempotente).
  Es la base del matching de patrones — no borrar.
- **IA**: implementada solo como desempate de área (`services/ia_area.py`, Haiku). El plan
  anterior de extraer ítems estructurados (`ItemFactura`) quedó superseded por el matching
  full-text, que es gratis. La key vive en `.env` como `API_KEY_IA_CLAUDE`.
- **Despliegue**: proyecto ya desplegado en Azure App Service (contenedor). n8n ya configurado
  apuntando a `POST /api/jobs/sync`. La tanda de 3 tipos de documento + firma universal +
  filtros ya salió a producción (commit "Segundo Deploy"); la migración de Azure SQL se corrió
  ANTES del deploy (orden crítico: `create_all()` no altera tablas existentes).
- **Cleanup pendiente (menor)**: `models.py` tiene una constante `ESTADOS_PROCESO` que quedó
  desactualizada (no incluye `procesada`/`aprobada`) — no se usa en ningún otro lado del
  backend (verificado por grep), es inofensiva pero conviene corregirla o borrarla si se toca
  esa zona.
- **`motion` (npm)**: se importa como `motion/react` (no `"motion"` a secas — ojo al buscarlo en
  el código). En uso en `Login.jsx` (tagline animado) y `Admin.jsx` (`AnimatePresence` para los
  modales de Roles/Áreas).

## Git

Repo en GitHub (`origin` → `https://github.com/Oscar095/Facturas.git`), rama por defecto y de
trabajo: `main`. El push a `main` dispara el deploy a Azure App Service (workflow de GitHub
Actions con publish profile — ver `.github/workflows/`). Commitear/pushear solo cuando el
usuario lo pida.

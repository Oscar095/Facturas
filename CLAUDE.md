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
3. **Modales atascados tumban la corrida en cascada.** Si un PDF tarda y queda un modal
   abierto, su backdrop tapa el botón "Buscar" del siguiente documento y fallan todos.
   `_cerrar_modales()` se llama antes de cada descarga (cierre amable + red de seguridad por JS
   que oculta modales/backdrops residuales). `descargar_pdf` además **reintenta hasta 3 veces**.
4. La sincronización es **idempotente**: dedup por CUFE (`_existe_cufe`). Reejecutar el mismo
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
  Ver `ReglaArea` en `models.py`.
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
  sea del usuario (404 si no) y **estampa la firma en todos los PDF adjuntos** de tipo
  FV/OCN/OCS/CRN (no OTRO) — en TODAS las páginas, abajo a la derecha, con texto
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
  apuntando a `POST /api/jobs/sync`.
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

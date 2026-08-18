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
tabla aparte `notas_credito` (**sí tienen área**, pero NO flujo de completitud/aprobación —
ver "Notas Crédito" abajo; blobs en `notas_credito/AAAA/MM/`). No se extraen Notas Débito
(`92`) — no se ha pedido.

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
5. **El login de v3.1.0.17 NO navega a otra URL.** Antes `_login()` esperaba
   `wait_for_url("**/documentRecepcion/**")`; desde la actualización del portal la pantalla de
   recepción se renderiza **dejando la URL en `#/login`**, así que esa espera reventaba con
   `Timeout 45000ms exceeded` aun con credenciales VÁLIDAS (se confundió con el problema de
   clave vencida que ocurrió el mismo día). Ahora se espera a que aparezca el **botón
   "Buscar"** de los filtros, que sí es señal confiable de sesión iniciada. Además el botón de
   login **ya no es `type=submit`** (llama `$ctrl.getToken()`): se intenta clic por texto
   "Iniciar Sesión", luego el submit clásico y por último Enter.
6. La sincronización es **idempotente**: dedup por CUFE (`_existe_cufe`). Reejecutar el mismo
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
- **Aprobar en bloque** (`POST /api/facturas/aprobar-lote`, body `{ids, firma_id}`): el jefe
  de área marca varias facturas en el listado y las firma de una vez, sin entrar a cada una.
  Las que aún no están `procesada` **se procesan en el mismo paso** (seleccionarlas ES la
  declaración humana equivalente al botón Procesar; queda su propio evento `procesada` con
  el detalle "procesada en aprobación por lote"). Se **omite sin abortar** lo que no se puede
  aprobar (sin área, ya aprobada/contabilizada, de otra área) y cada factura **se confirma por
  separado**: si una falla se hace rollback SOLO de esa y el lote sigue. La respuesta
  (`ResumenAprobacionLote`) detalla el motivo por factura para que la UI lo muestre. Tope
  `_MAX_LOTE = 100` porque firmar es caro (bajar + sellar + subir cada PDF). Reusa el mismo
  `_sellar_documentos()` que la aprobación individual — no duplicar la lógica de sellado.
- **Observaciones** (`PUT /api/facturas/{id}/observaciones`, `facturas.observaciones`): nota
  libre que escribe quien carga los documentos para el jefe que aprueba. Deliberadamente **NO
  exige `editar_facturas`** (que sí protege área/orden/responsable), solo acceso al área de la
  factura — mismo criterio que `routers/documentos.py`: quien sube la OCN debe poder
  explicarla. Texto en blanco la borra (queda NULL); tope 2000 chars (422); auditada como
  evento `observaciones`. Viaja en `FacturaResumen`, así el listado muestra el indicador 💬
  con la nota en el tooltip y el jefe la lee antes de aprobar en bloque.
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
- **Moneda extranjera (USD)**: la BD guarda `valor_total`/`iva` SIEMPRE en COP. Si la IA
  detecta factura en USD, extrae también la **TRM impresa en la factura** y el formulario la
  muestra para que el usuario la revise; al guardar, el backend convierte (USD × TRM,
  redondeo a centavos), exige TRM si `moneda=USD` (400 si falta) y deja trazabilidad en
  `facturas.moneda` / `trm` / `valor_original` (+ el evento `carga_manual` anota la
  conversión). Con `moneda=COP` la TRM se descarta. Migración:
  `scripts/migrar_moneda_vencimiento.py` (ya corrida en Azure SQL).
- **`facturas.fecha_vencimiento`**: la llena la carga manual (la IA la extrae) y también la
  ingesta del portal — ver "Fecha de vencimiento" abajo.

## Fecha de vencimiento (`services/vencimiento.py`)

- **El portal Siesa NO la expone** (verificado, no volver a intentarlo a ciegas): el JSON del
  listado tiene 23 claves y ninguna es de vencimiento (solo `FORMA_PAGO`: 1=contado/2=crédito);
  el menú de cada fila solo ofrece "Ver DIAN / Ver PDF / Ver Logs" — **no hay descarga de XML**;
  y el catálogo público de la DIAN (`catalogo-vpfe.dian.gov.co`, tanto `searchqr` como
  `DownloadZipFiles`) hoy **exige login**, así que tampoco sirve para sacar el `cbc:DueDate`
  del UBL. Herramientas del spike: `scripts/explorar_vencimiento.py` y
  `scripts/explorar_xml_portal.py`.
- Por eso se deduce del **texto del PDF** (`texto_pdf`, pypdf — gratis), en 3 niveles
  determinísticos + IA como último recurso (`resolver_vencimiento()`, la función que usan la
  ingesta y el backfill):
  1. Fecha junto a la etiqueta (venc. / "pague antes de" / límite de pago…), juntando **todas**
     las apariciones y tomando la más tardía: el layout en columnas suele dejar la etiqueta
     pegada a la EMISIÓN en un lado y al vencimiento en otro.
  2. Plazo de crédito escrito ("CREDITO 45 DIAS") sumado a la emisión.
  3. Si la etiqueta existe pero quedó lejos de su valor, la **única** fecha posterior a la
     emisión del documento; si hay varias es ambiguo y se deja NULL (nunca adivinar).
  4. **IA (Haiku, `services/vencimiento_ia.py`) — solo si `usar_ia`** y los 3 niveles fallaron.
     Manda solo el texto recortado, o el PDF **recortado a la 1ª página** si viene escaneado
     (visión cuesta por página). Queda auditado como evento `ia_vencimiento`.
- **Gotcha 1 — la vigencia de la resolución DIAN**: toda factura la imprime (rango de ~2 años).
  Por eso `_MAX_DIAS = 180` es deliberadamente ajustado; con una ventana amplia esa fecha se
  cuela como vencimiento. En los datos reales ningún plazo pasa de 120 días. No subir ese límite.
- **Gotcha 2 — la IA inventa el plazo típico**: comprobado en pruebas, ante una factura que NO
  dice el vencimiento, Haiku responde con seguridad "emisión + 30 días". Por eso se le exige
  citar el fragmento y `_respaldada_por_el_documento()` **verifica que la fecha exista de verdad
  en el texto** (o que salga de un plazo escrito); sin respaldo se descarta. No quitar esa
  verificación: sin ella entraron fechas falsas en las pruebas. En escaneadas no aplica (no hay
  texto que confrontar) — ahí se confía en la visión.
- Cobertura real: **87% del total** (432/498). Pruebas: `scripts/probar_vencimiento.py`
  (22 casos con fragmentos reales, incluidos los que DEBEN dar None). Backfill idempotente:
  `scripts/backfill_vencimiento.py [--ia] [--aplicar]` (solo toca filas NULL; sin `--ia` no
  gasta un peso). Costo medido con `scripts/estimar_costo_ia_vencimiento.py`: **~US$1/mes**.

## Listado de facturas

- `GET /api/facturas` filtra por `fecha_desde`/`fecha_hasta` sobre **`fecha_emision`** (no
  `fecha_recepcion`): la emisión se guarda tal cual la entrega el portal (hora local de
  Colombia), así que se compara directo. NO "corregir" esto a `fecha_recepcion` sin aplicar
  el desfase de Bogotá (esa columna sí está en UTC — ver gotcha del Dashboard).
- **Los filtros viven en la URL** (`useSearchParams` en `Facturas.jsx`), no en el estado del
  componente: al entrar a una factura y volver con ← la lista reaparece igual. Cada cambio de
  filtro va con `{ replace: true }` — si apilara entradas de historial, "Volver" tendría que
  deshacer tecleo por tecleo. Y se escribe con la **forma funcional** de `setParams`
  (`setParams(previos => …)`), no con el `qs` del render: dos campos cambiados muy seguido
  (p. ej. desde/hasta del rango) usarían una copia vieja y el segundo borraría al primero —
  esto ya ocurrió y lo destapó `probar_ui_tipos_fechas.py`.
- La **casilla de selección** de la 1ª columna solo se pinta para quien tiene el permiso
  `aprobar`; ojo con las pruebas de UI que indexan columnas por `nth-child` (se corrió una).
  La selección se limpia al cambiar de filtro o página (las filas marcadas ya no están a la
  vista) y el clic en la casilla hace `stopPropagation` para no abrir el detalle.

## Notas Crédito (`/notas-credito`, `routers/notas_credito.py`)

- **Sí tienen área/responsable** (`notas_credito.area_id` / `responsable_id`), pero **no**
  tienen `estado_proceso`, documentos, eventos ni flujo de aprobación: solo se consultan,
  se descarga el PDF y se sabe a qué área corresponde el crédito.
- **Asignación automática por reglas, SIN IA.** Comparte la cascada con las facturas —
  `reglas._resolver_regla()` es el núcleo común (NIT → patrones de ítem sobre `texto_pdf`) —
  pero se invoca vía `reglas.asignar_area_nota_credito()`, que pasa `usar_ia=False`.
  Decisión de negocio: **no gastar créditos de Claude en notas crédito**; lo que los patrones
  no decidan queda sin área para asignarse a mano. No ampliar esto sin que el usuario lo pida.
- Al no haber IA tampoco hay evento que auditar, y de todas formas no se podría:
  `eventos.factura_id` es un FK NOT NULL a `facturas.id`, así que **una nota crédito no puede
  escribir en `eventos`** tal como está el modelo hoy.
- **Asignación manual**: `PATCH /api/notas-credito/{id}` (permiso `editar_facturas`, el mismo
  que para editar facturas) con `{area_id}`. La UI es un dropdown por fila en el listado
  (no hay página de detalle de nota crédito).
- **Alcance por rol igual que en facturas**: con `ver_todas_areas` se ven todas; sin ese
  permiso, solo las del área del usuario (las que están sin asignar solo las ve quien ve
  todas). Por eso la ruta `/notas-credito` y el link del menú **ya no** están detrás de
  `ver_todas_areas` — el filtrado lo hace el backend (`_filtrar_por_rol`), no el frontend.
- Las notas crédito **históricas quedaron sin área** (decisión: no re-descargar el histórico
  del Blob para extraerles el texto). Se asignan a mano con el dropdown; el filtro
  `?sin_area=true` ("Solo sin área" en la UI) sirve justamente para irlas despachando.

## Dashboard (`/`, página de inicio)

- `GET /api/panel/dashboard?periodo=mes|trimestre|anio|todo&mes=AAAA-MM&meses=12`
  (`routers/panel.py`) alimenta `frontend/src/pages/Dashboard.jsx`: KPIs del mes elegido,
  compras por área (con "Sin asignar" destacado), la matriz **área × mes** y las facturas
  con más tiempo sin procesar.
- **`mes` (`AAAA-MM`) ancla todo el panel**, no solo las tarjetas: los periodos relativos
  terminan en él (`trimestre` = ese mes y los 2 previos; `anio` = enero→ese mes), así se
  puede analizar cualquier mes histórico. Por defecto es el mes en curso; un formato
  inválido responde 400. `meses_disponibles` (del primer documento al mes actual, tope
  `_MAX_MESES_SELECTOR`) alimenta el selector de la página.
- **La matriz agrupa por mes en Python, no en SQL** (`_clave_mes`): `DATEPART`/`strftime`
  darían el mes UTC y una factura recibida 19:00–23:59 hora Bogotá cae al día/mes siguiente
  en UTC. Además evita depender del dialecto (Azure SQL vs SQLite local). La ventana está
  acotada a `meses` (≤ 24), así que la consulta trae pocas filas.
- **Gotcha de zona horaria**: las fechas se guardan en UTC-naive pero el negocio opera en
  Bogotá (UTC-5, sin DST). Los cortes de mes/año se calculan en hora local y se convierten a
  UTC (`_DESFASE_BOGOTA = timedelta(hours=5)`, helpers `_rango_mes_utc`/`_sumar_meses`) antes
  de filtrar. Si se agregan más cortes de fecha al panel, seguir ese mismo patrón — comparar
  directo en UTC sin el desfase corta el mes en el momento equivocado.
- El mapa de calor usa una **rampa secuencial de un solo tono** (azul de marca, `.celda-n1..n5`
  en `styles.css`): claro→oscuro = más gasto, con texto blanco solo en el paso más oscuro.
  No convertirla en multicolor ni reusarla para categorías sin orden natural.
- El alcance por rol (`area` solo ve lo suyo) se resuelve con `tiene_permiso(db, usuario,
  "ver_todas_areas")`, igual que en `facturas.py` — no repetir el chequeo viejo
  `usuario.rol == "area"`.

## Secretos (NO commitear, NO imprimir)

- Todo lo sensible vive en **`.env`** (gitignored desde el primer commit): credenciales del
  portal Siesa, connection string del Data Lake, credenciales de Azure SQL, `JWT_SECRET`,
  `JOBS_API_KEY`. En la nube van como **App Settings** del App Service.
- No pegar valores de secretos en código, commits, ni en archivos versionados (incluido este).

## Estado / pendientes

- **Login Siesa: RESUELTO (2026-08-05)**. Fueron DOS problemas simultáneos tras la
  actualización a "Siesa E - Invoicing v3.1.0.17": (a) la contraseña dejó de ser válida — el
  usuario la restableció y actualizó `PASSWORD_FACTURAS` en `.env`; (b) `_login()` esperaba una
  navegación que en v3.1 ya no ocurre (ver gotcha 5). Con ambos arreglados la ingesta real
  corre de nuevo (verificado: 3 facturas nuevas, 0 errores). **Pendiente del usuario**:
  actualizar también `PASSWORD_FACTURAS` en los **App Settings del App Service**, o el robot
  de n8n seguirá fallando en la nube. El `#token_input` oculto + "VALIDAR TOKEN" del formulario
  NO se activó con credenciales válidas (no hay 2FA que manejar).
- **Scripts locales sin versionar** (herramientas de diagnóstico, misma máquina):
  `scripts/diagnosticar_login.py` (reproduce el login con screenshots/toasts/errores HTTP) y
  `scripts/ver_ultimo_log.py` (últimas 4 filas de `ejecuciones` con desglose de contadores).
- **Vencimiento de facturas escaneadas**: 149 facturas no tienen `texto_pdf` (PDF sin capa de
  texto), así que se quedan sin `fecha_vencimiento`. Resolverlas exigiría OCR o visión con IA
  — no hacerlo sin que el usuario lo pida (gasta créditos).
- **Reglas de área**: importadas 184 filas desde el Excel histórico (cruce de NIT por mayoría).
  Quedan ~34 proveedores con NIT ambiguo y ~9 sin NIT (en `reglas_area` con `proveedor_nit`
  NULL) y 17 con múltiples áreas candidatas — se completan a mano o cuando exista extracción IA.
- **Texto de facturas**: `facturas.texto_pdf` se llena en la ingesta (pypdf) y fue
  backfilleado para todas las facturas históricas (`scripts/migrar_texto_pdf.py`, idempotente).
  Es la base del matching de patrones — no borrar. `notas_credito.texto_pdf` existe igual pero
  **solo se llena de aquí en adelante**: las 15 notas históricas quedaron sin texto ni área
  (no se re-descargó el histórico del Blob) y se asignan a mano.
- **IA**: 3 usos, todos con Haiku y todos como ÚLTIMO recurso después de lo gratis —
  desempate de área (`services/ia_area.py`), extracción en la carga manual
  (`services/extraer_factura.py`, solo al pulsar el botón) y fecha de vencimiento
  (`services/vencimiento_ia.py`). La key vive en `.env` como `API_KEY_IA_CLAUDE`.
  Gasto medido del vencimiento: **~US$1/mes** a ~815 facturas/mes (Haiku 4.5 = US$1 por millón
  de tokens de entrada, US$5 de salida; el grueso es la visión de las escaneadas). Si hace
  falta una corrida sin gasto: `sincronizar(..., usar_ia_vencimiento=False)`.
- **Despliegue**: proyecto ya desplegado en Azure App Service (contenedor). n8n ya configurado
  apuntando a `POST /api/jobs/sync`. La tanda de 3 tipos de documento + firma universal +
  filtros ya salió a producción (commit "Segundo Deploy"); la migración de Azure SQL se corrió
  ANTES del deploy (orden crítico: `create_all()` no altera tablas existentes). Lo mismo aplica
  a `scripts/migrar_area_notas_credito.py` (área en notas crédito) — **ya corrido en Azure SQL**.
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

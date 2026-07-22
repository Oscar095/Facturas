# Portal de Recepción de Facturas Electrónicas (Siesa → Azure)

Automatiza la descarga diaria de facturas del portal **Siesa Smart4B**, las guarda en
**Azure Blob (Data Lake)** y **Azure SQL**, y ofrece un **portal web** (React + FastAPI)
para revisar el estado, asignar áreas responsables y cargar los documentos que faltan
para contabilizar (OCN/OCS/CRN).

## Arquitectura

```
n8n (schedule diario) ──POST /api/jobs/sync (x-api-key)──▶ Backend FastAPI (App Service, contenedor)
                                                            ├── Ingesta Playwright → portal Siesa
                                                            │     • descarga PDF (Ver PDF)
                                                            │     • sube a Azure Blob (datalakekos/facturas)
                                                            │     • inserta en Azure SQL (esquema 'facturas')
                                                            ├── API portal: auth JWT, facturas, documentos, áreas, usuarios
                                                            └── sirve el build de React
n8n ◀── resumen ──┘  →  correo Office 365 (nuevas / errores)
```

- **Ingesta**: descubierta y validada contra el portal real. El listado usa el endpoint
  interno `pst/listado/recepcion-proveedores` (JSON con todos los metadatos: folio,
  emisor, NIT, valor, CUFE, fecha, estado DIAN). El PDF se obtiene interceptando la
  respuesta de "Ver PDF" (`siesafe…:707/api/ConsultaCO/pdf-recepcion`).
- **Completitud**: FV (el PDF descargado) + orden (OCN u OCS); si es OCN, además CRN.
  Al completar → `lista_contabilizar`; contabilidad marca `contabilizada`.

## Estructura

| Carpeta | Contenido |
|---|---|
| `backend/app/ingesta/` | Cliente Siesa (`siesa_client.py`) y sincronización idempotente (`sincronizar.py`) |
| `backend/app/services/` | Almacenamiento Blob (`blob_storage.py`) y reglas de negocio (`reglas.py`) |
| `backend/app/routers/` | `auth`, `facturas`, `documentos`, `areas`, `usuarios`, `jobs`, `panel` |
| `backend/app/models.py` | Modelo de datos (SQLAlchemy) — esquema `facturas` en Azure SQL |
| `frontend/` | Portal React + Vite |
| `n8n/` | Workflow de ingesta diaria (ver `n8n/README.md`) |
| `scripts/` | Utilidades de exploración/pruebas (no van al contenedor) |

## Configuración (.env)

Copia `.env.example` a `.env`. Variables (acepta alias `BD_*` / `SQL_*`):

| Variable | Descripción |
|---|---|
| `URL_FACTURAS`, `USERNAME_FACTURAS`, `PASSWORD_FACTURAS` | Portal Siesa |
| `BD_HOST`, `BD_NAME`, `BD_USER`, `BD_PASSWORD` | Azure SQL (tablas en esquema `facturas`) |
| `AZURE_STORAGE_ACCOUNT` | Connection string del Data Lake (contenedor `facturas`) |
| `JWT_SECRET` | Firma de tokens (cadena larga aleatoria) |
| `JOBS_API_KEY` | Protege `/api/jobs/*` (lo usa n8n) |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Admin inicial (solo al crear la BD por primera vez) |

> Si `BD_HOST` está vacío, el backend usa **SQLite local** (`facturas_dev.db`) y
> guarda los archivos en `descargas/blob/` — útil para desarrollar sin Azure.

## Desarrollo local

```bash
# Backend
python -m venv .venv && .venv\Scripts\activate
pip install -r backend/requirements.txt
playwright install chromium
cd backend && python init_db.py          # crea esquema, tablas y admin
uvicorn app.main:app --reload --port 8000

# Frontend (otra terminal)
cd frontend && npm install && npm run dev  # http://localhost:5173 (proxy /api → :8000)
```

Ingesta manual de prueba (limitada):
```bash
python scripts/probar_ingesta.py 5        # descarga hasta 5 facturas nuevas
```

## Despliegue en Azure App Service (contenedor)

No necesitas Docker local: se compila en Azure Container Registry.

```bash
# 1. Recursos (ajusta nombres/grupo/región)
az group create -n rg-facturas -l eastus
az acr create  -n acrfacturaskos -g rg-facturas --sku Basic --admin-enabled true

# 2. Construir la imagen en la nube (usa el Dockerfile del repo)
az acr build -r acrfacturaskos -t facturas:latest .

# 3. Plan + Web App con la imagen del ACR
az appservice plan create -n plan-facturas -g rg-facturas --is-linux --sku B1
az webapp create -g rg-facturas -p plan-facturas -n facturas-kos \
  --deployment-container-image-name acrfacturaskos.azurecr.io/facturas:latest

# 4. Variables de entorno (App Settings) — NO subir el .env
az webapp config appsettings set -g rg-facturas -n facturas-kos --settings \
  URL_FACTURAS="https://portalfe.siesacloud.com/smart4b/#/login" \
  USERNAME_FACTURAS="..." PASSWORD_FACTURAS="..." \
  BD_HOST="myappskos.database.windows.net" BD_NAME="kx_ecommerce" \
  BD_USER="kos" BD_PASSWORD="..." \
  AZURE_STORAGE_ACCOUNT="DefaultEndpointsProtocol=...;AccountName=datalakekos;..." \
  JWT_SECRET="<aleatorio-largo>" JOBS_API_KEY="<clave-fuerte>" \
  ADMIN_EMAIL="oscar.orozco03@gmail.com" ADMIN_PASSWORD="<clave-admin>" \
  CORS_ORIGINS="https://facturas-kos.azurewebsites.net" \
  WEBSITES_PORT="8000"
```

Consideraciones:
- **Firewall de Azure SQL**: permite el acceso desde servicios de Azure (o la salida del App Service).
- El contenedor corre `init_db.py` al arrancar (crea esquema/tablas/admin si faltan) y luego uvicorn.
- Playwright/Chromium ya vienen en la imagen; el plan **B1** es suficiente para la ingesta diaria.

## n8n

Importa `n8n/workflow_ingesta_facturas.json` y configura `FACTURAS_API_URL`,
`FACTURAS_JOBS_API_KEY` y `FACTURAS_NOTIFICA_EMAIL`. Detalles en `n8n/README.md`.

## Pendientes del negocio
- Cargar el **Excel proveedor/ítem → área** (Administración → Áreas y reglas → Importar).
- Crear los **usuarios** por área y sus responsables.
- **Rotar** la contraseña del portal Siesa una vez estable (hoy está en el `.env`).

## Seguridad
- `.env` está en `.gitignore` desde el primer commit; en producción todo va por App Settings.
- Contraseñas de usuarios con PBKDF2-HMAC-SHA256 (200k iteraciones, salt por usuario).
- JWT con expiración; `/api/jobs/*` protegido por `JOBS_API_KEY`.

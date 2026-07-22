# ─────────────────────────────────────────────────────────────────────────────
# Etapa 1: compilar el frontend React
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ─────────────────────────────────────────────────────────────────────────────
# Etapa 2: backend FastAPI + Playwright + ODBC (imagen final)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app

# ODBC Driver 18 for SQL Server (para conectar a Azure SQL con pyodbc)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates apt-transport-https unixodbc \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python + navegador de Playwright (con sus libs del SO)
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt \
    && playwright install --with-deps chromium

# Código del backend y el frontend ya compilado
COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist ./frontend/dist

WORKDIR /app/backend
EXPOSE 8000
# Crea esquema/tablas/admin (idempotente) y arranca el servidor
CMD ["sh", "-c", "python init_db.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

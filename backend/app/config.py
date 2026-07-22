import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

# En local carga el .env de la raíz del repo; en Azure las variables llegan por App Settings
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _env(*nombres: str, default: str = "") -> str:
    """Devuelve la primera variable de entorno definida (soporta varios alias)."""
    for n in nombres:
        v = os.getenv(n)
        if v is not None and v.strip() != "":
            return v.strip()
    return default


class Settings:
    # Portal Siesa
    url_facturas: str = _env("URL_FACTURAS")
    username_facturas: str = _env("USERNAME_FACTURAS")
    password_facturas: str = _env("PASSWORD_FACTURAS")

    # Azure SQL  (acepta BD_* y SQL_* como alias)
    sql_server: str = _env("BD_HOST", "SQL_SERVER")
    sql_database: str = _env("BD_NAME", "SQL_DATABASE", default="facturas")
    sql_username: str = _env("BD_USER", "SQL_USERNAME")
    sql_password: str = _env("BD_PASSWORD", "SQL_PASSWORD")
    # Esquema donde viven las tablas de esta app (aísla de otras tablas de la BD)
    db_schema: str = _env("DB_SCHEMA", default="facturas")

    # Azure Blob  (AZURE_STORAGE_ACCOUNT contiene la connection string completa)
    storage_connection_string: str = _env(
        "AZURE_STORAGE_CONNECTION_STRING", "AZURE_STORAGE_ACCOUNT"
    )
    storage_container: str = _env("AZURE_STORAGE_CONTAINER", default="facturas")

    # API
    jwt_secret: str = _env("JWT_SECRET", default="cambia-esta-clave-en-produccion")
    jwt_expira_minutos: int = int(_env("JWT_EXPIRA_MINUTOS", default="480"))
    jobs_api_key: str = _env("JOBS_API_KEY", default="")

    # Driver ODBC a usar para SQL Server (18 o 17)
    odbc_driver: str = _env("ODBC_DRIVER", default="ODBC Driver 18 for SQL Server")

    @property
    def usa_sqlite(self) -> bool:
        return not self.sql_server

    @property
    def database_url(self) -> str:
        # SQLite local para desarrollo sin Azure SQL (SQL_SERVER/BD_HOST vacío)
        if self.usa_sqlite:
            return "sqlite:///./facturas_dev.db"
        odbc = (
            f"DRIVER={{{self.odbc_driver}}};"
            f"SERVER={self.sql_server},1433;DATABASE={self.sql_database};"
            f"UID={self.sql_username};PWD={self.sql_password};"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}"


settings = Settings()

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import settings  # noqa: E402

eng = create_engine(settings.database_url)
with eng.connect() as c:
    rows = c.execute(text(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = :s ORDER BY TABLE_NAME"
    ), {"s": settings.db_schema}).fetchall()
    print("Tablas en esquema", settings.db_schema, ":", [r[0] for r in rows])

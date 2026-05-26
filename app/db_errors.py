import psycopg2
from fastapi import HTTPException


def raise_if_db_error(exc: Exception) -> None:
    if isinstance(exc, psycopg2.OperationalError):
        raise HTTPException(
            status_code=503,
            detail=(
                "Base de données indisponible. "
                "Relancez : cd site-scraper && docker compose up --build"
            ),
        ) from exc
    raise exc

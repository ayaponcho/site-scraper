import psycopg2
import psycopg2.errors
from fastapi import HTTPException
_MIGRATION_HINT = (
    "Appliquez les migrations backend : "
    "migrations/20260526_site_scraper.sql puis "
    "migrations/20260867_scraper_sites_rss_keywords.sql "
    "(tables scraper_sites / scraper_articles + keywords RSS)."
)


def raise_if_db_error(exc: Exception) -> None:
    if isinstance(exc, psycopg2.OperationalError):
        raise HTTPException(
            status_code=503,
            detail=(
                "Base de données indisponible. "
                "Relancez : cd site-scraper && docker compose up --build"
            ),
        ) from exc
    if isinstance(exc, psycopg2.errors.UndefinedTable):
        raise HTTPException(
            status_code=503,
            detail=f"Tables scraper manquantes en base. {_MIGRATION_HINT}",
        ) from exc
    if isinstance(exc, psycopg2.ProgrammingError):
        msg = str(exc).lower()
        if "scraper_sites" in msg or "scraper_articles" in msg or "does not exist" in msg:
            raise HTTPException(
                status_code=503,
                detail=f"Schéma scraper absent ou incomplet. {_MIGRATION_HINT}",
            ) from exc
    # Erreurs scrape/réseau (403 Gartner, etc.) → JSON 502, pas un 500 ASGI
    from app.scrape_errors import raise_http_for_scrape_error

    raise_http_for_scrape_error(exc)

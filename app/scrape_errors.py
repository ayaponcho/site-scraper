import httpx
from fastapi import HTTPException

from app.db_errors import raise_if_db_error


def raise_http_for_scrape_error(exc: Exception) -> None:
    """Convertit erreurs réseau / HTTP du scrape en réponse JSON lisible par le front."""
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        url = str(exc.request.url)
        host = (exc.request.url.host or "").lower()
        if status == 403:
            if "reddit.com" in host:
                hint = (
                    "Reddit bloque souvent les IP datacenter (403). "
                    "Décochez ce flux pour scraper le reste, ou retirez-le de la thématique GEO."
                )
            elif "gartner.com" in host:
                hint = (
                    "Gartner bloque souvent les requêtes automatisées depuis un serveur. "
                    "Testez une autre source ou un proxy (SCRAPE_HTTP_PROXY)."
                )
            else:
                hint = (
                    "Le site refuse les requêtes automatisées depuis le serveur. "
                    "Réessayez plus tard ou retirez cette source de la sélection."
                )
            raise HTTPException(
                status_code=502,
                detail=f"Accès refusé (403) par le site source : {url}. {hint}",
            ) from exc
        if status == 404:
            raise HTTPException(
                status_code=502,
                detail=f"Page introuvable (404) : {url}",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=f"Erreur HTTP {status} lors du téléchargement : {url}",
        ) from exc
    if isinstance(exc, httpx.RequestError):
        raise HTTPException(
            status_code=502,
            detail=f"Erreur réseau lors du scrape : {exc}",
        ) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


def rethrow_as_http(exc: Exception) -> None:
    """Erreurs BDD puis scrape/réseau → HTTPException JSON pour le front."""
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        raise_if_db_error(exc)
    except HTTPException:
        raise
    except Exception as err:
        raise_http_for_scrape_error(err)

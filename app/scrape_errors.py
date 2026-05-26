import httpx
from fastapi import HTTPException


def raise_http_for_scrape_error(exc: Exception) -> None:
    """Convertit erreurs réseau / HTTP du scrape en réponse JSON lisible par le front."""
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        url = str(exc.request.url)
        if status == 403:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Accès refusé (403) par le site source : {url}. "
                    "Gartner bloque souvent les requêtes automatisées depuis un serveur. "
                    "Testez une autre source ou ajoutez un site avec le scraper « générique »."
                ),
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

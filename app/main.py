import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import check_db
from app.routes import articles, sites
from app.scrape_errors import rethrow_as_http
from app import service

logger = logging.getLogger(__name__)

APP_VERSION = "0.1.8"

app = FastAPI(
    title="Site Scraper API",
    description="Scraping de sites d'insights (Gartner, etc.) — prototype",
    version="0.1.0",
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]


def _cors_headers(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin")
    if not origin:
        return {}
    if origins and origin not in origins and "*" not in origins:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
    }


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Réponse JSON + CORS même sur erreur DB (évite « Failed to fetch » opaque)."""
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=_cors_headers(request),
        )
    try:
        rethrow_as_http(exc)
    except HTTPException as http_exc:
        return JSONResponse(
            status_code=http_exc.status_code,
            content={"detail": http_exc.detail},
            headers=_cors_headers(request),
        )
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )

app.include_router(sites.router, prefix="/v1")
app.include_router(articles.router, prefix="/v1")


@app.get("/health")
def health():
    return {"status": "ok", "database": check_db(), "version": APP_VERSION}


@app.post("/v1/scrape-all")
async def scrape_all(background: BackgroundTasks, sync: bool = False):
    if sync:
        results = await service.scrape_all_enabled()
        return {"results": results}

    async def _job():
        await service.scrape_all_enabled()

    background.add_task(_job)
    return {"status": "started"}

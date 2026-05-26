import logging

from fastapi import APIRouter, BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import check_db
from app.routes import articles, sites
from app import service

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Site Scraper API",
    description="Scraping de sites d'insights (Gartner, etc.) — prototype",
    version="0.1.0",
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sites.router, prefix="/v1")
app.include_router(articles.router, prefix="/v1")


@app.get("/health")
def health():
    return {"status": "ok", "database": check_db()}


@app.post("/v1/scrape-all")
async def scrape_all(background: BackgroundTasks, sync: bool = False):
    if sync:
        results = await service.scrape_all_enabled()
        return {"results": results}

    async def _job():
        await service.scrape_all_enabled()

    background.add_task(_job)
    return {"status": "started"}

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app import service
from app.db_errors import raise_if_db_error
from app.schemas import ScrapeResult, SiteCreate, SiteOut, SiteUpdate

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("", response_model=dict)
def get_sites():
    try:
        sites = service.list_sites()
    except Exception as exc:
        raise_if_db_error(exc)
    return {"sites": [SiteOut(**site) for site in sites]}


@router.post("", response_model=dict, status_code=201)
def post_site(body: SiteCreate):
    try:
        site = service.create_site(
            name=body.name.strip(),
            url=str(body.url),
            scraper_type=body.scraper_type,
            enabled=body.enabled,
        )
    except Exception as exc:
        raise_if_db_error(exc)
    return {"site": SiteOut(**site)}


@router.get("/{site_id}", response_model=dict)
def get_site(site_id: int):
    try:
        site = service.get_site(site_id)
    except Exception as exc:
        raise_if_db_error(exc)
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")
    return {"site": SiteOut(**site)}


@router.patch("/{site_id}", response_model=dict)
def patch_site(site_id: int, body: SiteUpdate):
    try:
        site = service.update_site(site_id, body.model_dump(exclude_unset=True))
    except Exception as exc:
        raise_if_db_error(exc)
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")
    return {"site": SiteOut(**site)}


@router.delete("/{site_id}", status_code=204)
def remove_site(site_id: int):
    try:
        deleted = service.delete_site(site_id)
    except Exception as exc:
        raise_if_db_error(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Site introuvable")


async def _run_scrape(site_id: int):
    await service.scrape_site(site_id)


@router.post("/{site_id}/scrape", response_model=ScrapeResult)
async def scrape_one(site_id: int, background: BackgroundTasks, sync: bool = Query(False)):
    try:
        site = service.get_site(site_id)
    except Exception as exc:
        raise_if_db_error(exc)
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")

    if sync:
        try:
            return ScrapeResult(**await service.scrape_site(site_id))
        except Exception as exc:
            raise_if_db_error(exc)

    background.add_task(_run_scrape, site_id)
    return ScrapeResult(site_id=site_id, new_articles=0, updated_articles=0, total_found=0)

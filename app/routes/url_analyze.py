from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.landing_audit import build_landing_audit
from app.schemas import ArticleAnalysisOut
from app.scrapers.analyze import analyze_article_page

router = APIRouter(tags=["analyze"])


class AnalyzeUrlBody(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class AnalyzeUrlAuditBody(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    kind: str = Field(default="service", max_length=32)


def _validate_url(raw: str) -> str:
    url = str(raw or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL invalide — doit commencer par http:// ou https://")
    return url


async def _analyze_payload(url: str) -> dict:
    payload = await analyze_article_page(url)
    analyzed_at = datetime.now(timezone.utc)
    fields = payload.get("fields") or []
    warnings = list(payload.get("warnings") or [])
    if not fields and not warnings:
        warnings.append("Aucun contenu structuré détecté sur cette page.")
    return {
        "article_id": 0,
        "url": url,
        "analyzed_at": analyzed_at,
        "persisted": False,
        "http_status": int(payload.get("http_status") or 0),
        "fields": fields,
        "dates_found": payload.get("dates_found") or [],
        "sections": payload.get("sections") or [],
        "tags": payload.get("tags") or [],
        "warnings": warnings,
    }


@router.post("/analyze-url", response_model=dict)
async def analyze_url(body: AnalyzeUrlBody):
    url = _validate_url(body.url)
    result = await _analyze_payload(url)
    return {"analysis": ArticleAnalysisOut(**result)}


@router.post("/analyze-url/audit", response_model=dict)
async def analyze_url_audit(body: AnalyzeUrlAuditBody):
    url = _validate_url(body.url)
    kind = str(body.kind or "service").strip().lower()
    if kind not in ("evergreen", "product", "service", "event"):
        kind = "service"

    scrape = await _analyze_payload(url)
    audit = await build_landing_audit(url, kind, scrape)
    return {
        "analysis": ArticleAnalysisOut(**scrape),
        "audit": audit,
    }

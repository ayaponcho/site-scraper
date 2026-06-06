from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.schemas import ArticleAnalysisOut
from app.scrapers.analyze import analyze_article_page

router = APIRouter(tags=["analyze"])


class AnalyzeUrlBody(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


@router.post("/analyze-url", response_model=dict)
async def analyze_url(body: AnalyzeUrlBody):
    raw = str(body.url or "").strip()
    if not raw.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL invalide — doit commencer par http:// ou https://")

    payload = await analyze_article_page(raw)
    analyzed_at = datetime.now(timezone.utc)
    fields = payload.get("fields") or []
    warnings = list(payload.get("warnings") or [])
    if not fields and not warnings:
        warnings.append("Aucun contenu structuré détecté sur cette page.")

    result = {
        "article_id": 0,
        "url": raw,
        "analyzed_at": analyzed_at,
        "persisted": False,
        "http_status": int(payload.get("http_status") or 0),
        "fields": fields,
        "dates_found": payload.get("dates_found") or [],
        "sections": payload.get("sections") or [],
        "tags": payload.get("tags") or [],
        "warnings": warnings,
    }
    return {"analysis": ArticleAnalysisOut(**result)}

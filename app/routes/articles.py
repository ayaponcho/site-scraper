from fastapi import APIRouter, HTTPException, Query

from app import service
from app.db_errors import raise_if_db_error
from app.schemas import (
    ArticleAnalysisOut,
    ArticleOut,
    AnalysisFieldsUpdateBody,
    AnalysisKeyPointsUpdateBody,
)

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=dict)
def get_articles(
    site_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, description="Recherche titre / insights / URL"),
    keyword: str | None = Query(default=None, description="Mot-clé dans titre ou insights"),
    has_analysis: bool | None = Query(default=None),
    scraper_type: str | None = Query(default=None, description="generic | gartner | rss"),
    since_hours: int | None = Query(default=None, ge=1, le=24 * 90),
):
    try:
        rows, total = service.list_articles(
            site_id=site_id,
            limit=limit,
            offset=offset,
            q=q,
            keyword=keyword,
            has_analysis=has_analysis,
            scraper_type=scraper_type,
            since_hours=since_hours,
        )
    except Exception as exc:
        raise_if_db_error(exc)
    articles = []
    for row in rows:
        payload = dict(row)
        payload.pop("site_scraper_type", None)
        articles.append(ArticleOut(**payload))
    return {
        "articles": articles,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{article_id}", response_model=dict)
def get_article(article_id: int):
    try:
        row = service.get_article(article_id)
    except Exception as exc:
        raise_if_db_error(exc)
    if not row:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return {"article": ArticleOut(**row)}


@router.patch("/{article_id}/analysis", response_model=dict)
def patch_article_analysis(article_id: int, body: AnalysisFieldsUpdateBody):
    try:
        result = service.update_article_analysis_fields(
            article_id,
            [f.model_dump() for f in body.fields],
        )
    except ValueError as exc:
        if str(exc) == "Article not found":
            raise HTTPException(status_code=404, detail="Article introuvable") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_if_db_error(exc)
    return {"analysis": ArticleAnalysisOut(**result)}


@router.patch("/{article_id}/analysis/key-points", response_model=dict)
def patch_article_analysis_key_points(article_id: int, body: AnalysisKeyPointsUpdateBody):
    try:
        result = service.update_article_analysis_key_points(article_id, body.key_points)
    except ValueError as exc:
        if str(exc) == "Article not found":
            raise HTTPException(status_code=404, detail="Article introuvable") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_if_db_error(exc)
    return {"analysis": ArticleAnalysisOut(**result)}


@router.post("/{article_id}/analyze", response_model=dict)
async def analyze_article(
    article_id: int,
    persist: bool = Query(default=True, description="Enregistrer l'analyse en BDD (published_at, insights, analysis_json)"),
    refetch: bool = Query(
        default=False,
        description="Re-télécharger la page HTML (désactivé par défaut : analyse le contenu déjà scrapé)",
    ),
):
    try:
        result = await service.analyze_article(article_id, persist=persist, refetch=refetch)
    except ValueError as exc:
        if str(exc) == "Article not found":
            raise HTTPException(status_code=404, detail="Article introuvable") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_if_db_error(exc)
    return {"analysis": ArticleAnalysisOut(**result)}

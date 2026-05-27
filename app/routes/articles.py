from fastapi import APIRouter, HTTPException, Query

from app import service
from app.db_errors import raise_if_db_error
from app.schemas import ArticleAnalysisOut, ArticleOut, AnalysisFieldsUpdateBody

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=dict)
def get_articles(
    site_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        rows, total = service.list_articles(site_id=site_id, limit=limit, offset=offset)
    except Exception as exc:
        raise_if_db_error(exc)
    return {
        "articles": [ArticleOut(**row) for row in rows],
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


@router.post("/{article_id}/analyze", response_model=dict)
async def analyze_article(
    article_id: int,
    persist: bool = Query(default=True, description="Enregistrer l'analyse en BDD (published_at, insights, analysis_json)"),
):
    try:
        result = await service.analyze_article(article_id, persist=persist)
    except ValueError as exc:
        if str(exc) == "Article not found":
            raise HTTPException(status_code=404, detail="Article introuvable") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_if_db_error(exc)
    return {"analysis": ArticleAnalysisOut(**result)}

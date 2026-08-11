from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


ScraperType = Literal["generic", "gartner", "rss"]
KeywordsMode = Literal["any", "all"]


def _clean_keywords(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        k = str(raw).strip()
        if not k:
            continue
        key = k.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(k)
    return out


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    scraper_type: ScraperType = "generic"
    enabled: bool = True
    keywords: list[str] = Field(default_factory=list)
    keywords_mode: KeywordsMode = "any"

    @field_validator("keywords", mode="before")
    @classmethod
    def coerce_keywords(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            parts = re_split_keywords(v)
            return parts
        if isinstance(v, list):
            return [str(x) for x in v]
        return []

    @model_validator(mode="after")
    def validate_rss_keywords(self) -> "SiteCreate":
        self.keywords = _clean_keywords(self.keywords)
        if self.scraper_type == "rss" and not self.keywords:
            raise ValueError("Au moins un mot-clé est obligatoire pour un flux RSS")
        return self


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: HttpUrl | None = None
    scraper_type: ScraperType | None = None
    enabled: bool | None = None
    keywords: list[str] | None = None
    keywords_mode: KeywordsMode | None = None

    @field_validator("keywords", mode="before")
    @classmethod
    def coerce_keywords(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, str):
            return re_split_keywords(v)
        if isinstance(v, list):
            return [str(x) for x in v]
        return None

    @model_validator(mode="after")
    def validate_rss_keywords(self) -> "SiteUpdate":
        if self.keywords is not None:
            self.keywords = _clean_keywords(self.keywords)
        if self.scraper_type == "rss" and self.keywords is not None and not self.keywords:
            raise ValueError("Au moins un mot-clé est obligatoire pour un flux RSS")
        return self


def re_split_keywords(raw: str) -> list[str]:
    parts: list[str] = []
    for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
        k = chunk.strip()
        if k:
            parts.append(k)
    return parts


class SiteOut(BaseModel):
    id: int
    name: str
    url: str
    scraper_type: ScraperType
    enabled: bool
    last_scraped_at: datetime | None
    created_at: datetime
    article_count: int = 0
    keywords: list[str] = Field(default_factory=list)
    keywords_mode: KeywordsMode = "any"


class ArticleOut(BaseModel):
    id: int
    site_id: int
    site_name: str | None = None
    title: str
    url: str
    insights: str | None
    published_at: datetime | None
    scraped_at: datetime
    analysis_json: dict[str, Any] | None = None


class ScrapeResult(BaseModel):
    site_id: int
    new_articles: int
    updated_articles: int
    total_found: int


class AnalysisFieldOut(BaseModel):
    key: str
    label: str
    value: str | int | float | None = None
    raw: str | None = None
    source: str
    confidence: float


class AnalysisFieldUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=200)
    value: str | int | float | None = None
    raw: str | None = None
    source: str | None = Field(default="manual", max_length=200)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AnalysisFieldsUpdateBody(BaseModel):
    fields: list[AnalysisFieldUpdate] = Field(min_length=1)


class AnalysisKeyPointsUpdateBody(BaseModel):
    key_points: dict[str, Any]


class AnalysisDateOut(BaseModel):
    kind: str
    raw: str
    parsed: str | None = None
    source: str
    confidence: float


class AnalysisSectionOut(BaseModel):
    type: str
    text: str
    level: int | None = None
    index: int | None = None


class ArticleAnalysisOut(BaseModel):
    article_id: int
    url: str
    analyzed_at: datetime
    persisted: bool
    http_status: int
    fields: list[AnalysisFieldOut]
    dates_found: list[AnalysisDateOut]
    sections: list[AnalysisSectionOut]
    tags: list[str]
    warnings: list[str]
    key_points: dict[str, Any] | None = None

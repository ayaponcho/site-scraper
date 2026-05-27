from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


ScraperType = Literal["generic", "gartner"]


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    scraper_type: ScraperType = "generic"
    enabled: bool = True


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: HttpUrl | None = None
    scraper_type: ScraperType | None = None
    enabled: bool | None = None


class SiteOut(BaseModel):
    id: int
    name: str
    url: str
    scraper_type: ScraperType
    enabled: bool
    last_scraped_at: datetime | None
    created_at: datetime
    article_count: int = 0


class ArticleOut(BaseModel):
    id: int
    site_id: int
    site_name: str | None = None
    title: str
    url: str
    insights: str | None
    published_at: datetime | None
    scraped_at: datetime


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

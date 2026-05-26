from dataclasses import dataclass
from datetime import datetime


@dataclass
class ScrapedArticle:
    title: str
    url: str
    insights: str | None = None
    published_at: datetime | None = None

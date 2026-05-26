import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedArticle
from app.scrapers.generic import fetch_article_insights, fetch_html

logger = logging.getLogger(__name__)


def _detect_gartner_type(url: str) -> str:
    path = urlparse(url).path.lower()
    if "/marketing/" in path or path.endswith("/marketing"):
        return "marketing"
    return "insights"


async def scrape_gartner_listing(list_url: str, fetch_insights: bool = True) -> list[ScrapedArticle]:
    html = await fetch_html(list_url)
    soup = BeautifulSoup(html, "lxml")
    base_host = urlparse(list_url).netloc
    seen: set[str] = set()
    articles: list[ScrapedArticle] = []

    selectors = [
        "a[href*='/marketing/']",
        "a[href*='/insights/']",
        "a[href*='/articles/']",
        "article a[href]",
        ".card a[href]",
        "[data-testid*='card'] a[href]",
    ]

    candidates = []
    for selector in selectors:
        candidates.extend(soup.select(selector))

    for anchor in candidates:
        href = anchor.get("href", "")
        url = urljoin(list_url, href.split("?")[0].split("#")[0].rstrip("/"))
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc != base_host:
            continue
        if url in seen:
            continue

        path = parsed.path.lower()
        if not re.search(r"/(marketing|insights|articles)/", path):
            continue
        if path.endswith("/marketing") or path.endswith("/insights"):
            continue

        title = anchor.get_text(" ", strip=True)
        title = re.sub(r"\s+", " ", title)
        if len(title) < 10:
            heading = anchor.find_previous(["h1", "h2", "h3", "h4"])
            if heading:
                title = heading.get_text(" ", strip=True)

        if len(title) < 10:
            continue

        seen.add(url)
        insights = None
        if fetch_insights:
            insights = await fetch_article_insights(url)

        articles.append(ScrapedArticle(title=title[:500], url=url, insights=insights))

    if not articles:
        logger.info("Gartner parser found nothing, falling back to generic for %s", list_url)
        from app.scrapers.generic import scrape_generic_listing

        return await scrape_generic_listing(list_url, fetch_insights=fetch_insights)

    return articles

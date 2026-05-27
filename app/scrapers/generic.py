import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.scrape_errors import raise_http_for_scrape_error
from app.scrapers.base import ScrapedArticle
from app.url_utils import canonical_article_url

logger = logging.getLogger(__name__)

ARTICLE_PATH_HINTS = (
    "/article/",
    "/articles/",
    "/insights/",
    "/blog/",
    "/news/",
    "/research/",
    "/report/",
    "/webinar/",
    "/podcast/",
)


def _normalize_url(base: str, href: str) -> str | None:
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    absolute = urljoin(base, href.split("?")[0].split("#")[0].rstrip("/"))
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    return absolute


LISTING_PATH_EXCLUDES = (
    "/tag/",
    "/category/",
    "/author/",
    "/page/",
    "/search/",
    "/newsletter",
)


def _looks_like_article(url: str, base_host: str) -> bool:
    parsed = urlparse(url)
    base_norm = base_host.lower().removeprefix("www.")
    host_norm = (parsed.netloc or "").lower().removeprefix("www.")
    if host_norm and host_norm != base_norm:
        return False
    path = parsed.path.lower()
    if any(ex in path for ex in LISTING_PATH_EXCLUDES):
        return False
    if path.startswith("/reports/tag"):
        return False
    if "datareportal.com" in host_norm:
        if not path.startswith("/reports/") or path.startswith("/reports/tag"):
            return False
    if any(hint in path for hint in ARTICLE_PATH_HINTS):
        return True
    segments = [s for s in path.split("/") if s]
    if len(segments) >= 3 and segments[-1] not in ("marketing", "insights", "en"):
        return True
    return False


def _extract_insights_from_soup(soup: BeautifulSoup) -> str | None:
    for selector in (
        'meta[name="description"]',
        'meta[property="og:description"]',
        'meta[name="twitter:description"]',
    ):
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            text = tag["content"].strip()
            if len(text) > 40:
                return text

    for selector in (
        "article p",
        ".article-body p",
        ".content p",
        "main p",
        "p",
    ):
        paragraphs = [
            p.get_text(" ", strip=True)
            for p in soup.select(selector)
            if len(p.get_text(strip=True)) > 60
        ]
        if paragraphs:
            return " ".join(paragraphs[:3])[:2000]
    return None


async def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    parsed = urlparse(url)
    if parsed.netloc.endswith("gartner.com"):
        headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"

    async with httpx.AsyncClient(
        timeout=settings.scrape_timeout_seconds,
        follow_redirects=True,
        headers=headers,
        proxy=settings.scrape_http_proxy or None,
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except Exception as exc:
            raise_http_for_scrape_error(exc)
        return response.text


async def fetch_article_insights(url: str) -> str | None:
    try:
        html = await fetch_html(url)
        soup = BeautifulSoup(html, "lxml")
        return _extract_insights_from_soup(soup)
    except Exception as exc:
        logger.warning("Could not fetch insights for %s: %s", url, exc)
        return None


async def scrape_generic_listing(list_url: str, fetch_insights: bool = True) -> list[ScrapedArticle]:
    html = await fetch_html(list_url)
    soup = BeautifulSoup(html, "lxml")
    base_host = urlparse(list_url).netloc
    seen: set[str] = set()
    articles: list[ScrapedArticle] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        url = _normalize_url(list_url, href)
        if not url or url in seen:
            continue

        title = anchor.get_text(" ", strip=True)
        title = re.sub(r"\s+", " ", title)
        if len(title) < 12:
            parent = anchor.find_parent(["h1", "h2", "h3", "h4", "article", "li"])
            if parent:
                title = parent.get_text(" ", strip=True)
                title = re.sub(r"\s+", " ", title)

        if len(title) < 12 or not _looks_like_article(url, base_host):
            continue

        url = canonical_article_url(url)
        if url in seen:
            continue

        seen.add(url)
        insights = None
        if fetch_insights:
            insights = await fetch_article_insights(url)

        articles.append(ScrapedArticle(title=title[:500], url=url, insights=insights))

    return articles

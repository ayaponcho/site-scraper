"""Ingestion flux RSS / Atom → ScrapedArticle (summary nettoyé → insights)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import mktime

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from app.config import settings
from app.scrape_errors import raise_http_for_scrape_error
from app.scrapers.base import ScrapedArticle
from app.url_utils import canonical_article_url

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


def _html_to_text(raw: str | None) -> str:
    if not raw or not str(raw).strip():
        return ""
    soup = BeautifulSoup(str(raw), "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return _WS_RE.sub(" ", text).strip()


def _normalize_keywords(keywords: list[str] | None) -> list[str]:
    return [k.strip().lower() for k in (keywords or []) if k and str(k).strip()]


def _item_matches(
    haystack: str,
    keywords: list[str],
    mode: str,
) -> bool:
    if not keywords:
        return False
    text = (haystack or "").lower()
    hits = [kw for kw in keywords if kw in text]
    if mode == "all":
        return len(hits) == len(keywords)
    return len(hits) > 0


def _parse_published(entry: dict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
            except (OverflowError, ValueError, TypeError, OSError):
                pass
    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            return parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            pass
        try:
            dt = date_parser.parse(str(raw))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError, OverflowError):
            continue
    return None


def _entry_link(entry: dict) -> str | None:
    link = (entry.get("link") or "").strip()
    if link:
        return link
    links = entry.get("links") or []
    for item in links:
        href = (item.get("href") or "").strip()
        if href and item.get("rel") in (None, "", "alternate"):
            return href
    for item in links:
        href = (item.get("href") or "").strip()
        if href:
            return href
    return None


def _entry_summary(entry: dict) -> str:
    for key in ("summary", "description"):
        text = _html_to_text(entry.get(key))
        if text:
            return text[:4000]
    content = entry.get("content")
    if isinstance(content, list):
        for block in content:
            text = _html_to_text(block.get("value") if isinstance(block, dict) else None)
            if text:
                return text[:4000]
    return ""


def _entry_categories(entry: dict) -> list[str]:
    tags: list[str] = []
    for t in entry.get("tags") or []:
        term = (t.get("term") or t.get("label") or "").strip()
        if term:
            tags.append(term)
    return tags


async def scrape_rss_feed(
    feed_url: str,
    keywords: list[str],
    keywords_mode: str = "any",
) -> list[ScrapedArticle]:
    """Fetch + parse un flux RSS/Atom ; filtre par keywords (obligatoires)."""
    kw = _normalize_keywords(keywords)
    if not kw:
        raise ValueError("Au moins un mot-clé est obligatoire pour un flux RSS")

    mode = keywords_mode if keywords_mode in ("any", "all") else "any"

    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    }

    async with httpx.AsyncClient(
        timeout=settings.scrape_timeout_seconds,
        follow_redirects=True,
        headers=headers,
        proxy=settings.scrape_http_proxy or None,
    ) as client:
        try:
            response = await client.get(feed_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise_http_for_scrape_error(exc)

    parsed = feedparser.parse(response.content)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        detail = getattr(parsed, "bozo_exception", None)
        raise ValueError(f"Flux RSS illisible: {detail or 'parse error'}")

    articles: list[ScrapedArticle] = []
    seen: set[str] = set()

    for entry in parsed.entries or []:
        link = _entry_link(entry)
        if not link:
            continue
        url = canonical_article_url(link)
        if url in seen:
            continue

        title = _html_to_text(entry.get("title")) or url
        summary = _entry_summary(entry)
        categories = _entry_categories(entry)
        haystack = " ".join([title, summary, " ".join(categories)])

        if not _item_matches(haystack, kw, mode):
            continue

        seen.add(url)
        articles.append(
            ScrapedArticle(
                title=title[:500],
                url=url,
                insights=summary or None,
                published_at=_parse_published(entry),
            )
        )

    logger.info(
        "RSS %s: %s entrées brutes → %s après filtre keywords=%s mode=%s",
        feed_url,
        len(parsed.entries or []),
        len(articles),
        kw,
        mode,
    )
    return articles

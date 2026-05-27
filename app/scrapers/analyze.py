"""Analyse approfondie d'une page article (métadonnées, dates, sections)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from app.scrapers.generic import _extract_insights_from_soup, fetch_html

logger = logging.getLogger(__name__)

DATE_KIND_PUBLISHED = "published"
DATE_KIND_MODIFIED = "modified"
DATE_KIND_UNKNOWN = "unknown"

PUBLISHED_HINTS = ("publish", "posted", "publi", "datepublished", "article:published")
MODIFIED_HINTS = ("modif", "updated", "update", "lastmod", "revision")


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_date(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text or len(text) < 4:
        return None
    try:
        dt = date_parser.parse(text, fuzzy=True)
        if dt.year < 1990 or dt.year > 2100:
            return None
        return dt
    except (ValueError, OverflowError, TypeError):
        return None


def _guess_date_kind(source: str, raw: str = "") -> str:
    blob = f"{source} {raw}".lower()
    if any(h in blob for h in MODIFIED_HINTS):
        return DATE_KIND_MODIFIED
    if any(h in blob for h in PUBLISHED_HINTS):
        return DATE_KIND_PUBLISHED
    return DATE_KIND_UNKNOWN


def _meta_content(soup: BeautifulSoup, selector: str) -> str | None:
    tag = soup.select_one(selector)
    if tag and tag.get("content"):
        text = tag["content"].strip()
        return text or None
    return None


def _json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            objects.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                objects.extend(item for item in data["@graph"] if isinstance(item, dict))
            else:
                objects.append(data)
    return objects


def _article_json_ld(objects: list[dict[str, Any]]) -> dict[str, Any] | None:
    article_types = {"article", "newsarticle", "blogposting", "scholarlyarticle", "report"}
    for obj in objects:
        t = obj.get("@type")
        types: list[str] = []
        if isinstance(t, str):
            types = [t.lower()]
        elif isinstance(t, list):
            types = [str(x).lower() for x in t]
        if any(any(at in ty for at in article_types) for ty in types):
            return obj
    for obj in objects:
        if obj.get("datePublished") or obj.get("headline"):
            return obj
    return None


def _extract_authors(article_ld: dict[str, Any] | None, soup: BeautifulSoup) -> str | None:
    if article_ld:
        author = article_ld.get("author")
        names: list[str] = []
        if isinstance(author, str):
            names.append(author)
        elif isinstance(author, dict):
            if author.get("name"):
                names.append(str(author["name"]))
        elif isinstance(author, list):
            for item in author:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]))
        if names:
            return ", ".join(dict.fromkeys(names))

    for selector in ('meta[name="author"]', '[rel="author"]', ".author", ".byline"):
        tag = soup.select_one(selector)
        if tag:
            text = tag.get("content") if tag.name == "meta" else tag.get_text(" ", strip=True)
            if text and len(text.strip()) > 2:
                return text.strip()[:300]
    return None


def _extract_title(soup: BeautifulSoup, article_ld: dict[str, Any] | None) -> tuple[str | None, str, float]:
    if article_ld and article_ld.get("headline"):
        return str(article_ld["headline"]).strip()[:500], "json-ld.headline", 0.93

    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(" ", strip=True)
        if len(text) >= 5:
            return text[:500], "h1", 0.92

    og = _meta_content(soup, 'meta[property="og:title"]')
    if og and len(og) >= 5:
        return og[:500], 'meta[property="og:title"]', 0.88

    if soup.title and soup.title.string:
        text = soup.title.string.strip()
        if len(text) >= 5:
            return text[:500], "title", 0.75

    return None, "", 0.0


def _collect_dates(soup: BeautifulSoup, article_ld: dict[str, Any] | None) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(raw: str, source: str, kind: str | None = None, confidence: float = 0.8):
        raw = (raw or "").strip()
        if not raw:
            return
        key = (raw[:80], source)
        if key in seen:
            return
        seen.add(key)
        parsed_dt = _parse_date(raw)
        date_kind = kind or _guess_date_kind(source, raw)
        conf = confidence
        if parsed_dt is None:
            conf = min(conf, 0.35)
        found.append(
            {
                "kind": date_kind,
                "raw": raw[:200],
                "parsed": _utc_iso(parsed_dt) if parsed_dt else None,
                "source": source,
                "confidence": round(conf, 2),
            }
        )

    if article_ld:
        if article_ld.get("datePublished"):
            add(str(article_ld["datePublished"]), "json-ld.datePublished", DATE_KIND_PUBLISHED, 0.95)
        if article_ld.get("dateModified"):
            add(str(article_ld["dateModified"]), "json-ld.dateModified", DATE_KIND_MODIFIED, 0.9)
        if article_ld.get("dateCreated"):
            add(str(article_ld["dateCreated"]), "json-ld.dateCreated", DATE_KIND_PUBLISHED, 0.85)

    meta_dates = (
        ('meta[property="article:published_time"]', DATE_KIND_PUBLISHED, 0.95),
        ('meta[property="article:modified_time"]', DATE_KIND_MODIFIED, 0.9),
        ('meta[name="pubdate"]', DATE_KIND_PUBLISHED, 0.85),
        ('meta[name="publish-date"]', DATE_KIND_PUBLISHED, 0.85),
        ('meta[name="date"]', DATE_KIND_PUBLISHED, 0.8),
        ('meta[property="og:updated_time"]', DATE_KIND_MODIFIED, 0.82),
        ('meta[name="last-modified"]', DATE_KIND_MODIFIED, 0.8),
    )
    for selector, kind, conf in meta_dates:
        val = _meta_content(soup, selector)
        if val:
            add(val, selector, kind, conf)

    for time_tag in soup.find_all("time"):
        raw = time_tag.get("datetime") or time_tag.get_text(" ", strip=True)
        classes = " ".join(time_tag.get("class", []))
        source = f"time[{classes or 'datetime'}]"
        add(raw, source, None, 0.78)

    for selector in (
        "[itemprop=datePublished]",
        "[itemprop=dateModified]",
        ".published",
        ".publish-date",
        ".post-date",
        ".article-date",
        ".entry-date",
        "[class*=publish]",
        "[class*=date]",
    ):
        for tag in soup.select(selector)[:3]:
            raw = tag.get("datetime") or tag.get("content") or tag.get_text(" ", strip=True)
            if raw and len(raw) >= 6:
                add(raw[:120], selector, None, 0.55)

    found.sort(key=lambda d: d["confidence"], reverse=True)
    return found


def _best_date(dates: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    for item in dates:
        if item["kind"] == kind and item.get("parsed"):
            return item
    for item in dates:
        if item.get("parsed"):
            return item
    return None


def _extract_tags(soup: BeautifulSoup, article_ld: dict[str, Any] | None) -> list[str]:
    tags: list[str] = []
    if article_ld:
        kw = article_ld.get("keywords")
        if isinstance(kw, str):
            tags.extend(k.strip() for k in kw.split(",") if k.strip())
        elif isinstance(kw, list):
            tags.extend(str(k).strip() for k in kw if str(k).strip())

    keywords = _meta_content(soup, 'meta[name="keywords"]')
    if keywords:
        tags.extend(k.strip() for k in keywords.split(",") if k.strip())

    for anchor in soup.select('a[rel="tag"], a[href*="/tag/"], a[href*="/tags/"]')[:12]:
        text = anchor.get_text(" ", strip=True)
        if text and 2 < len(text) < 60:
            tags.append(text)

    return list(dict.fromkeys(tags))[:20]


def _extract_sections(soup: BeautifulSoup) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    root = soup.select_one("article") or soup.select_one("main") or soup.body
    if not root:
        return sections

    for tag in root.find_all(["h2", "h3", "p", "li"], recursive=True):
        if tag.name in ("h2", "h3"):
            text = tag.get_text(" ", strip=True)
            if len(text) >= 4:
                sections.append({"type": "heading", "level": int(tag.name[1]), "text": text[:500]})
        elif tag.name == "p":
            text = tag.get_text(" ", strip=True)
            if len(text) >= 40:
                sections.append({"type": "paragraph", "index": len(sections), "text": text[:1200]})
        elif tag.name == "li":
            text = tag.get_text(" ", strip=True)
            if len(text) >= 20:
                sections.append({"type": "list_item", "index": len(sections), "text": text[:400]})
        if len(sections) >= 20:
            break
    return sections


def _word_count(soup: BeautifulSoup) -> int:
    root = soup.select_one("article") or soup.select_one("main") or soup.body
    if not root:
        return 0
    text = root.get_text(" ", strip=True)
    return len(re.findall(r"\w+", text))


def _field(
    key: str,
    label: str,
    value: str | int | float | None,
    source: str,
    confidence: float,
    raw: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "key": key,
        "label": label,
        "value": value,
        "source": source,
        "confidence": round(confidence, 2),
    }
    if raw is not None:
        row["raw"] = raw
    return row


async def analyze_article_page(url: str) -> dict[str, Any]:
    """Fetch and parse a single article URL; returns structured JSON for UI/API."""
    warnings: list[str] = []
    http_status = 200

    try:
        html = await fetch_html(url)
    except Exception as exc:
        logger.warning("Analyze fetch failed for %s: %s", url, exc)
        return {
            "url": url,
            "http_status": 0,
            "fields": [],
            "dates_found": [],
            "sections": [],
            "tags": [],
            "warnings": [f"Impossible de charger la page : {exc}"],
        }

    soup = BeautifulSoup(html, "lxml")
    json_ld = _json_ld_objects(soup)
    article_ld = _article_json_ld(json_ld)

    title, title_source, title_conf = _extract_title(soup, article_ld)
    dates_found = _collect_dates(soup, article_ld)
    pub = _best_date(dates_found, DATE_KIND_PUBLISHED)
    mod = _best_date(dates_found, DATE_KIND_MODIFIED)
    if mod and pub and mod.get("parsed") == pub.get("parsed"):
        mod = next((d for d in dates_found if d["kind"] == DATE_KIND_MODIFIED and d.get("parsed")), None)

    description = (
        _meta_content(soup, 'meta[property="og:description"]')
        or _meta_content(soup, 'meta[name="description"]')
        or _meta_content(soup, 'meta[name="twitter:description"]')
    )
    insights = _extract_insights_from_soup(soup)
    author = _extract_authors(article_ld, soup)
    canonical = None
    canon_tag = soup.find("link", rel=lambda v: v and "canonical" in v)
    if canon_tag and canon_tag.get("href"):
        canonical = urljoin(url, canon_tag["href"])
    og_image = _meta_content(soup, 'meta[property="og:image"]')
    lang = soup.html.get("lang") if soup.html else None
    tags = _extract_tags(soup, article_ld)
    sections = _extract_sections(soup)
    words = _word_count(soup)
    reading_min = max(1, round(words / 200)) if words else None

    fields: list[dict[str, Any]] = []
    if title:
        fields.append(_field("title", "Titre", title, title_source, title_conf))
    if pub:
        fields.append(
            _field(
                "published_at",
                "Date de publication",
                pub["parsed"],
                pub["source"],
                pub["confidence"],
                raw=pub["raw"],
            )
        )
    if mod and mod.get("parsed") != (pub or {}).get("parsed"):
        fields.append(
            _field(
                "modified_at",
                "Dernière modification",
                mod["parsed"],
                mod["source"],
                mod["confidence"],
                raw=mod["raw"],
            )
        )
    if author:
        fields.append(_field("author", "Auteur(s)", author, "json-ld.author" if article_ld else ".author", 0.85))
    if description:
        fields.append(
            _field("description", "Description", description[:2000], 'meta[property="og:description"]', 0.9)
        )
    if insights:
        fields.append(_field("insights", "Extrait principal", insights[:2000], "article p / meta", 0.75))
    if reading_min:
        fields.append(
            _field(
                "reading_time_minutes",
                "Temps de lecture (estimé)",
                reading_min,
                "word_count / 200",
                0.6,
            )
        )
    if canonical:
        fields.append(_field("canonical_url", "URL canonique", canonical, "link[rel=canonical]", 0.98))
    if og_image:
        fields.append(_field("og_image", "Image principale", og_image, 'meta[property="og:image"]', 0.9))
    if lang:
        fields.append(_field("language", "Langue", lang[:12], "html[lang]", 0.95))
    if words:
        fields.append(_field("word_count", "Nombre de mots", words, "article|main text", 0.7))

    if not dates_found:
        warnings.append("Aucune date de publication détectée sur la page.")
    if not insights and not description:
        warnings.append("Aucun extrait textuel exploitable (meta ou paragraphes).")

    return {
        "url": url,
        "http_status": http_status,
        "fields": fields,
        "dates_found": dates_found,
        "sections": sections,
        "tags": tags,
        "warnings": warnings,
    }

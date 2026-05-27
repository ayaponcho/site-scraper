import logging
from datetime import datetime, timezone

from app.db import db_cursor
from app.scrapers.analyze import analyze_article_page
from app.scrapers.base import ScrapedArticle
from app.scrapers.gartner import scrape_gartner_listing
from app.scrapers.generic import scrape_generic_listing
from app.url_utils import canonical_article_url

logger = logging.getLogger(__name__)


def _row_to_site(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "scraper_type": row["scraper_type"],
        "enabled": row["enabled"],
        "last_scraped_at": row["last_scraped_at"],
        "created_at": row["created_at"],
        "article_count": row.get("article_count", 0),
    }


def list_sites() -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT s.*, COUNT(a.id)::int AS article_count
            FROM scraper_sites s
            LEFT JOIN scraper_articles a ON a.site_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            """
        )
        return [_row_to_site(row) for row in cur.fetchall()]


def get_site(site_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT s.*, COUNT(a.id)::int AS article_count
            FROM scraper_sites s
            LEFT JOIN scraper_articles a ON a.site_id = s.id
            WHERE s.id = %s
            GROUP BY s.id
            """,
            (site_id,),
        )
        row = cur.fetchone()
        return _row_to_site(row) if row else None


def create_site(name: str, url: str, scraper_type: str, enabled: bool) -> dict:
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO scraper_sites (name, url, scraper_type, enabled)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (name, url, scraper_type, enabled),
        )
        row = cur.fetchone()
        return _row_to_site({**row, "article_count": 0})


def update_site(site_id: int, fields: dict) -> dict | None:
    allowed = {"name", "url", "scraper_type", "enabled"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_site(site_id)

    set_clause = ", ".join(f"{key} = %({key})s" for key in updates)
    updates["id"] = site_id

    with db_cursor() as cur:
        cur.execute(
            f"""
            UPDATE scraper_sites
            SET {set_clause}, updated_at = now()
            WHERE id = %(id)s
            RETURNING *
            """,
            updates,
        )
        row = cur.fetchone()
        return get_site(site_id) if row else None


def delete_site(site_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("DELETE FROM scraper_sites WHERE id = %s RETURNING id", (site_id,))
        return cur.fetchone() is not None


def list_articles(site_id: int | None, limit: int, offset: int) -> tuple[list[dict], int]:
    params: list = []
    where = ""
    if site_id is not None:
        where = "WHERE a.site_id = %s"
        params.append(site_id)

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)::int AS total
            FROM scraper_articles a
            {where}
            """,
            params,
        )
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT a.*, s.name AS site_name
            FROM scraper_articles a
            JOIN scraper_sites s ON s.id = a.site_id
            {where}
            ORDER BY a.scraped_at DESC
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows], total


def get_article(article_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT a.*, s.name AS site_name
            FROM scraper_articles a
            JOIN scraper_sites s ON s.id = a.site_id
            WHERE a.id = %s
            """,
            (article_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


async def _scrape_site_listing(site: dict, fetch_insights: bool) -> list[ScrapedArticle]:
    scraper_type = site["scraper_type"]
    list_url = site["url"]
    if scraper_type == "gartner" or "gartner.com" in list_url:
        return await scrape_gartner_listing(list_url, fetch_insights=fetch_insights)
    return await scrape_generic_listing(list_url, fetch_insights=fetch_insights)


def _upsert_articles(site_id: int, articles: list[ScrapedArticle]) -> tuple[int, int]:
    new_count = 0
    updated_count = 0
    now = datetime.now(timezone.utc)

    with db_cursor() as cur:
        cur.execute(
            "SELECT id, title, insights, url FROM scraper_articles WHERE site_id = %s",
            (site_id,),
        )
        by_canonical: dict[str, dict] = {}
        for row in cur.fetchall():
            by_canonical[canonical_article_url(row["url"])] = dict(row)

        for article in articles:
            canon = canonical_article_url(article.url)
            article.url = canon
            existing = by_canonical.get(canon)
            if existing:
                changed = (
                    existing["title"] != article.title
                    or (article.insights and existing["insights"] != article.insights)
                )
                if changed:
                    cur.execute(
                        """
                        UPDATE scraper_articles
                        SET title = %s, url = %s, insights = COALESCE(%s, insights), scraped_at = %s
                        WHERE id = %s
                        """,
                        (article.title, canon, article.insights, now, existing["id"]),
                    )
                    updated_count += 1
                    by_canonical[canon] = {**existing, "title": article.title, "insights": article.insights}
            else:
                cur.execute(
                    """
                    INSERT INTO scraper_articles (site_id, title, url, insights, published_at, scraped_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        site_id,
                        article.title,
                        canon,
                        article.insights,
                        article.published_at,
                        now,
                    ),
                )
                row_id = cur.fetchone()["id"]
                new_count += 1
                by_canonical[canon] = {
                    "id": row_id,
                    "title": article.title,
                    "insights": article.insights,
                    "url": canon,
                }

        cur.execute(
            "UPDATE scraper_sites SET last_scraped_at = %s, updated_at = %s WHERE id = %s",
            (now, now, site_id),
        )

    return new_count, updated_count


def dedupe_articles(site_id: int | None = None) -> dict:
    """Supprime les doublons (URL canonique, puis titre identique) en gardant la plus ancienne ligne."""
    removed_url = 0
    removed_title = 0

    with db_cursor() as cur:
        where = ""
        params: list = []
        if site_id is not None:
            where = "WHERE site_id = %s"
            params.append(site_id)

        cur.execute(
            f"""
            SELECT id, site_id, title, url
            FROM scraper_articles
            {where}
            ORDER BY id ASC
            """,
            params,
        )
        rows = cur.fetchall()

        seen_canon: dict[tuple[int, str], int] = {}
        delete_ids: set[int] = set()

        for row in rows:
            key = (row["site_id"], canonical_article_url(row["url"]))
            if key in seen_canon:
                delete_ids.add(row["id"])
                removed_url += 1
            else:
                seen_canon[key] = row["id"]

        remaining = [r for r in rows if r["id"] not in delete_ids]
        seen_title: dict[tuple[int, str], int] = {}
        for row in remaining:
            title_key = (row["site_id"], (row["title"] or "").strip().lower())
            if not title_key[1]:
                continue
            if title_key in seen_title:
                delete_ids.add(row["id"])
                removed_title += 1
            else:
                seen_title[title_key] = row["id"]

        for aid in delete_ids:
            cur.execute("DELETE FROM scraper_articles WHERE id = %s", (aid,))

    return {
        "removed_duplicates": len(delete_ids),
        "removed_by_url": removed_url,
        "removed_by_title": removed_title,
    }


async def scrape_site(site_id: int, fetch_insights: bool = True) -> dict:
    site = get_site(site_id)
    if not site:
        raise ValueError("Site not found")

    articles = await _scrape_site_listing(site, fetch_insights=fetch_insights)
    new_count, updated_count = _upsert_articles(site_id, articles)
    return {
        "site_id": site_id,
        "new_articles": new_count,
        "updated_articles": updated_count,
        "total_found": len(articles),
    }


def _field_value(fields: list[dict], key: str) -> str | None:
    for row in fields:
        if row.get("key") == key and row.get("value") is not None:
            return str(row["value"])
    return None


def _field_confidence(fields: list[dict], key: str) -> float:
    for row in fields:
        if row.get("key") == key:
            return float(row.get("confidence") or 0)
    return 0.0


def _persist_analysis(article_id: int, fields: list[dict]) -> None:
    published_raw = _field_value(fields, "published_at")
    insights = _field_value(fields, "insights")
    title = _field_value(fields, "title")
    title_conf = _field_confidence(fields, "title")
    now = datetime.now(timezone.utc)

    published_at = None
    if published_raw:
        try:
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE scraper_articles
            SET
              published_at = COALESCE(%s, published_at),
              insights = COALESCE(%s, insights),
              title = CASE WHEN %s AND %s IS NOT NULL THEN %s ELSE title END,
              scraped_at = %s
            WHERE id = %s
            """,
            (
                published_at,
                insights,
                title_conf >= 0.9,
                title,
                title,
                now,
                article_id,
            ),
        )


async def analyze_article(article_id: int, persist: bool = False) -> dict:
    article = get_article(article_id)
    if not article:
        raise ValueError("Article not found")

    payload = await analyze_article_page(article["url"])
    analyzed_at = datetime.now(timezone.utc)

    if persist and payload.get("fields"):
        _persist_analysis(article_id, payload["fields"])

    return {
        "article_id": article_id,
        "url": article["url"],
        "analyzed_at": analyzed_at,
        "persisted": bool(persist and payload.get("fields")),
        "http_status": payload.get("http_status", 0),
        "fields": payload.get("fields") or [],
        "dates_found": payload.get("dates_found") or [],
        "sections": payload.get("sections") or [],
        "tags": payload.get("tags") or [],
        "warnings": payload.get("warnings") or [],
    }


async def scrape_all_enabled(fetch_insights: bool = True) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM scraper_sites WHERE enabled = true ORDER BY id")
        sites = cur.fetchall()

    results = []
    for site in sites:
        try:
            result = await scrape_site(site["id"], fetch_insights=fetch_insights)
            results.append(result)
        except Exception as exc:
            logger.exception("Scrape failed for site %s: %s", site["id"], exc)
            results.append(
                {
                    "site_id": site["id"],
                    "error": str(exc),
                    "new_articles": 0,
                    "updated_articles": 0,
                    "total_found": 0,
                }
            )
    return results

import logging
from datetime import datetime, timezone

from app.db import db_cursor
from app.scrapers.base import ScrapedArticle
from app.scrapers.gartner import scrape_gartner_listing
from app.scrapers.generic import scrape_generic_listing

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
        for article in articles:
            cur.execute(
                "SELECT id, title, insights FROM scraper_articles WHERE site_id = %s AND url = %s",
                (site_id, article.url),
            )
            existing = cur.fetchone()
            if existing:
                changed = (
                    existing["title"] != article.title
                    or (article.insights and existing["insights"] != article.insights)
                )
                if changed:
                    cur.execute(
                        """
                        UPDATE scraper_articles
                        SET title = %s, insights = COALESCE(%s, insights), scraped_at = %s
                        WHERE id = %s
                        """,
                        (article.title, article.insights, now, existing["id"]),
                    )
                    updated_count += 1
            else:
                cur.execute(
                    """
                    INSERT INTO scraper_articles (site_id, title, url, insights, published_at, scraped_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        site_id,
                        article.title,
                        article.url,
                        article.insights,
                        article.published_at,
                        now,
                    ),
                )
                new_count += 1

        cur.execute(
            "UPDATE scraper_sites SET last_scraped_at = %s, updated_at = %s WHERE id = %s",
            (now, now, site_id),
        )

    return new_count, updated_count


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

import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from app.config import settings

logger = logging.getLogger(__name__)


def get_connection():
    return psycopg2.connect(settings.database_url)


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_db() -> bool:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception as exc:
        logger.warning("Database unavailable: %s", exc)
        return False

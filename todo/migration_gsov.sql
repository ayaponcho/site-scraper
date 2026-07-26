-- Migration : table gsov_results
-- À exécuter sur la base sendit (port 5434)
-- docker exec -i site-scraper-db-1 psql -U postgres -d sendit < migration_gsov.sql

CREATE TABLE IF NOT EXISTS gsov_results (
    id                   SERIAL PRIMARY KEY,
    article_id           INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    brand                TEXT NOT NULL,
    intent_label         TEXT,
    query                TEXT,
    llm_response         TEXT,
    explicit_mention     BOOLEAN DEFAULT FALSE,
    comparative_mention  BOOLEAN DEFAULT FALSE,
    prominence           TEXT CHECK (prominence IN ('primary','alternative','passing','none')),
    citation_rationale   TEXT,
    score                INTEGER CHECK (score BETWEEN 0 AND 3),
    confidence           INTEGER CHECK (confidence BETWEEN 0 AND 100),
    gsov_percent         NUMERIC(5,2),
    created_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gsov_article ON gsov_results(article_id);
CREATE INDEX IF NOT EXISTS idx_gsov_brand   ON gsov_results(brand);

-- Vue agrégée par article + marque
CREATE OR REPLACE VIEW gsov_summary AS
SELECT
    article_id,
    brand,
    COUNT(*)                          AS intent_count,
    SUM(score)                        AS total_score,
    (COUNT(*) * 3)                    AS max_score,
    ROUND(SUM(score)::numeric / NULLIF(COUNT(*)*3,0) * 100, 1) AS gsov_percent,
    ROUND(AVG(confidence), 0)         AS avg_confidence,
    SUM(CASE WHEN prominence='primary'     THEN 1 ELSE 0 END) AS primary_count,
    SUM(CASE WHEN prominence='alternative' THEN 1 ELSE 0 END) AS alternative_count,
    SUM(CASE WHEN prominence='passing'     THEN 1 ELSE 0 END) AS passing_count,
    SUM(CASE WHEN prominence='none'        THEN 1 ELSE 0 END) AS gap_count,
    MAX(created_at)                   AS last_run
FROM gsov_results
GROUP BY article_id, brand;

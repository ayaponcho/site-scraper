"""
gsov_runner.py — Intent Simulation G-SoV
Branche sur le Site Scraper existant (port 3020 / PostgreSQL 5434).

Usage:
  python gsov_runner.py --site_id 1 --brand "TargetSocial" --intents 6
  python gsov_runner.py --article_id 42 --brand "TargetSocial"

Dépendances:
  pip install anthropic psycopg2-binary httpx python-dotenv
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
import psycopg2
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────

SCRAPER_API   = os.getenv("SCRAPER_API_URL", "http://127.0.0.1:3020")
DATABASE_URL  = os.getenv("DATABASE_URL",
                "postgresql://postgres:postgres@127.0.0.1:5434/sendit")
ANTHROPIC_MODEL = "claude-sonnet-4-6"

SCORE_MAP = {"primary": 3, "alternative": 2, "passing": 1, "none": 0}

# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Article:
    id: int
    title: str
    url: str
    insights: str

@dataclass
class IntentResult:
    intent_label: str
    query: str
    llm_response: str
    explicit_mention: bool
    comparative_mention: bool
    recommendation_prominence: str   # primary | alternative | passing | none
    citation_rationale: str
    score: int
    confidence: int                  # 0-100

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS gsov_results (
            id              SERIAL PRIMARY KEY,
            article_id      INTEGER NOT NULL,
            brand           TEXT NOT NULL,
            intent_label    TEXT,
            query           TEXT,
            llm_response    TEXT,
            explicit_mention    BOOLEAN,
            comparative_mention BOOLEAN,
            prominence          TEXT,
            citation_rationale  TEXT,
            score               INTEGER,
            confidence          INTEGER,
            gsov_percent        NUMERIC(5,2),
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
        """)
        conn.commit()

def save_results(conn, article_id: int, brand: str,
                 results: list[IntentResult], gsov: float):
    with conn.cursor() as cur:
        for r in results:
            cur.execute("""
            INSERT INTO gsov_results
              (article_id, brand, intent_label, query, llm_response,
               explicit_mention, comparative_mention, prominence,
               citation_rationale, score, confidence, gsov_percent)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                article_id, brand, r.intent_label, r.query, r.llm_response,
                r.explicit_mention, r.comparative_mention,
                r.recommendation_prominence, r.citation_rationale,
                r.score, r.confidence, gsov
            ))
        conn.commit()

# ── Scraper API ───────────────────────────────────────────────────────────────

def fetch_articles(site_id: Optional[int] = None,
                   article_id: Optional[int] = None) -> list[Article]:
    with httpx.Client(base_url=SCRAPER_API, timeout=15) as client:
        if article_id:
            r = client.get(f"/v1/articles/{article_id}")
            r.raise_for_status()
            d = r.json()
            return [Article(d["id"], d["title"], d["url"],
                            d.get("insights") or "")]
        else:
            params = {"limit": 50}
            if site_id:
                params["site_id"] = site_id
            r = client.get("/v1/articles", params=params)
            r.raise_for_status()
            return [Article(a["id"], a["title"], a["url"],
                            a.get("insights") or "")
                    for a in r.json().get("items", r.json())]

# ── Claude calls ──────────────────────────────────────────────────────────────

def generate_intents(client: Anthropic, article: Article,
                     brand: str, n: int) -> list[dict]:
    """Demande à Claude de générer N intents réalistes depuis l'article."""
    prompt = f"""
Tu es un expert GEO (Generative Engine Optimization).
À partir de l'article suivant, génère exactement {n} requêtes utilisateur réalistes
qui pourraient amener un LLM à mentionner (ou non) la marque "{brand}".

Titre : {article.title}
URL   : {article.url}
Extrait : {article.insights[:800]}

Règles :
- Couvre le funnel : awareness, consideration, decision, fidélisation
- Au moins 1 intent générique (faible déclencheur marque)
- Au moins 2 intents à fort déclencheur commercial (comparatif, outil, solution)
- Langue : français, registre pro B2B
- Formulations variées (courtes, longues, question directe, recherche info)

Réponds UNIQUEMENT en JSON valide, tableau de {n} objets :
[{{"label": "...", "query": "...", "funnel_stage": "awareness|consideration|decision|retention"}}]
"""
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)

def simulate_and_score(client: Anthropic, intent: dict,
                       brand: str, article: Article) -> IntentResult:
    """Simule la réponse LLM puis détecte et score les signaux G-SoV."""
    prompt = f"""
Tu es un moteur d'analyse GEO.

ÉTAPE 1 — Simule la réponse probable d'un LLM généraliste à cette requête :
Requête : "{intent['query']}"
Contexte article disponible : titre="{article.title}", insights="{article.insights[:400]}"

La réponse simulée doit être vraisemblable (ton neutre, informatif, 3-6 phrases).
Elle peut mentionner ou non la marque "{brand}" selon la pertinence réelle.

ÉTAPE 2 — Analyse la réponse simulée et détecte les 4 signaux G-SoV pour la marque "{brand}" :
- explicit_mention : le nom exact de la marque est cité (true/false)
- comparative_mention : citée dans un comparatif d'alternatives (true/false)
- recommendation_prominence : "primary" (1re recommandation) | "alternative" | "passing" | "none"
- citation_rationale : pourquoi la marque est citée (1 phrase courte, ou "non mentionnée")

ÉTAPE 3 — Score et confiance :
- score : 3 (primary) | 2 (alternative) | 1 (passing) | 0 (none)
- confidence : 0-100 (probabilité que la réponse simulée soit réaliste)

Réponds UNIQUEMENT en JSON valide :
{{
  "llm_response": "...",
  "explicit_mention": true|false,
  "comparative_mention": true|false,
  "recommendation_prominence": "primary|alternative|passing|none",
  "citation_rationale": "...",
  "score": 0|1|2|3,
  "confidence": 0-100
}}
"""
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    d = json.loads(text)
    return IntentResult(
        intent_label    = intent["label"],
        query           = intent["query"],
        llm_response    = d["llm_response"],
        explicit_mention        = d["explicit_mention"],
        comparative_mention     = d["comparative_mention"],
        recommendation_prominence = d["recommendation_prominence"],
        citation_rationale      = d["citation_rationale"],
        score      = d["score"],
        confidence = d["confidence"],
    )

# ── Main ──────────────────────────────────────────────────────────────────────

def run_gsov(article: Article, brand: str, n_intents: int):
    client = Anthropic()  # utilise ANTHROPIC_API_KEY de l'env
    conn   = get_conn()
    ensure_table(conn)

    print(f"\n[G-SoV] Article #{article.id} — {article.title[:60]}")
    print(f"        Marque : {brand} | Intents : {n_intents}\n")

    # 1. Génération des intents
    print("  → Génération des intents...")
    intents = generate_intents(client, article, brand, n_intents)

    # 2. Simulation + scoring
    results: list[IntentResult] = []
    for i, intent in enumerate(intents, 1):
        print(f"  [{i}/{n_intents}] {intent['label']} — {intent['query'][:55]}...")
        r = simulate_and_score(client, intent, brand, article)
        results.append(r)
        print(f"         score={r.score} | conf={r.confidence}% | {r.recommendation_prominence}")
        time.sleep(0.3)  # throttle léger

    # 3. Calcul G-SoV
    total_score = sum(r.score for r in results)
    max_score   = n_intents * 3
    gsov        = round(total_score / max_score * 100, 1) if max_score else 0

    # 4. Sauvegarde
    save_results(conn, article.id, brand, results, gsov)
    conn.close()

    # 5. Résumé console
    print(f"\n  ━━ Résultats G-SoV ━━")
    print(f"  Score total     : {total_score} / {max_score}")
    print(f"  G-SoV           : {gsov}%")
    print(f"  Mentions prim.  : {sum(1 for r in results if r.recommendation_prominence=='primary')}")
    print(f"  Alternatives    : {sum(1 for r in results if r.recommendation_prominence=='alternative')}")
    print(f"  Conf. moyenne   : {round(sum(r.confidence for r in results)/len(results))}%")
    print(f"  Sauvegardé dans : gsov_results (article_id={article.id})\n")
    return gsov

def main():
    parser = argparse.ArgumentParser(description="G-SoV Intent Simulation Runner")
    parser.add_argument("--site_id",    type=int, help="Scraper les articles d'un site")
    parser.add_argument("--article_id", type=int, help="Un seul article")
    parser.add_argument("--brand",      required=True, help="Marque à analyser")
    parser.add_argument("--intents",    type=int, default=6,
                        help="Nombre d'intents par article (défaut: 6)")
    args = parser.parse_args()

    if not args.site_id and not args.article_id:
        print("Erreur : fournir --site_id ou --article_id")
        sys.exit(1)

    articles = fetch_articles(args.site_id, args.article_id)
    print(f"  {len(articles)} article(s) récupéré(s)")

    for article in articles:
        run_gsov(article, args.brand, args.intents)

if __name__ == "__main__":
    main()

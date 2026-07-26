# G-SoV Intent Runner

Script Python qui branche sur le **Site Scraper** existant pour tester
`intentSimulation` en conditions réelles.

## Installation

```bash
cd d:/dev/docker/site-scraper
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r gsov_runner/requirements.txt
cp gsov_runner/.env.example gsov_runner/.env
# → renseigner ANTHROPIC_API_KEY dans .env
```

## Pré-requis

Le stack Docker doit tourner :

```bash
docker compose up --build
# API scraper  → http://127.0.0.1:3020/health
# PostgreSQL   → 127.0.0.1:5434/sendit
```

## Migration DB (une seule fois)

```bash
docker exec -i site-scraper-db-1 psql -U postgres -d sendit \
  < gsov_runner/migration_gsov.sql
```

## Utilisation

```bash
# Analyser tous les articles d'un site
python gsov_runner/gsov_runner.py --site_id 1 --brand "TargetSocial" --intents 6

# Un seul article
python gsov_runner/gsov_runner.py --article_id 42 --brand "TargetSocial"

# Benchmark multi-marques
python gsov_runner/gsov_runner.py --site_id 1 --brand "Taplio" --intents 6
python gsov_runner/gsov_runner.py --site_id 1 --brand "Shield Analytics" --intents 6
```

## Lire les résultats

```bash
docker exec -it site-scraper-db-1 psql -U postgres -d sendit -c \
  "SELECT article_id, brand, gsov_percent, avg_confidence, primary_count
   FROM gsov_summary ORDER BY gsov_percent DESC;"
```

## Schéma des tables

```
articles         (existant scraper)
  └── gsov_results
        id, article_id, brand
        intent_label, query, llm_response
        explicit_mention, comparative_mention
        prominence (primary|alternative|passing|none)
        citation_rationale, score, confidence
        gsov_percent, created_at

gsov_summary     (vue agrégée)
        article_id, brand, intent_count
        total_score, max_score, gsov_percent
        avg_confidence, primary/alternative/passing/gap counts
```

## Coût API estimé

| Config | Tokens/run | Coût estimé |
|--------|-----------|-------------|
| 1 article × 6 intents | ~8 000 tokens | ~$0.024 |
| 10 articles × 6 intents | ~80 000 tokens | ~$0.24 |
| 50 articles × 6 intents | ~400 000 tokens | ~$1.20 |

Modèle : `claude-sonnet-4-6` (input $3/Mtok, output $15/Mtok).

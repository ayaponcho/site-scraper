# Site Scraper — prototype

Service Docker dédié au scraping de pages listing (Gartner Marketing, etc.) : récupération du **titre**, de l’**URL** et des **insights** (meta description / extrait) en base PostgreSQL.

## Démarrage rapide

### 1. Lancer PostgreSQL + API (tout-en-un)

```bash
cd d:/dev/docker/site-scraper
docker compose up --build
```

Le compose démarre :
- **PostgreSQL** sur le port hôte `5434` (base `sendit`, tables créées automatiquement)
- **API scraper** sur http://127.0.0.1:3020/health

### 2. Migration manuelle (seulement si vous utilisez une base externe)

Si vous préférez la base `tgm-deploy-db` au lieu du Postgres embarqué :

```bash
docker exec -i tgm-deploy-db psql -U postgres -d sendit < ../backend/migrations/20260526_site_scraper.sql
```

Puis dans `docker-compose.yml`, remplacez `DATABASE_URL` par votre URL et commentez le service `db`.

### 3. Interface Vue (front-tgm)

Le proxy Vite `/site-scraper-api` pointe vers le port **3020**.

```bash
cd d:/dev/vuejs/front-tgm
npm run dev
```

Pages :
- `/tools/scraper/sites` — ajouter / scraper des sites
- `/tools/scraper/articles` — liste + détail (titre, URL, insights)

## API

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/v1/sites` | Liste des sites |
| POST | `/v1/sites` | Créer un site |
| POST | `/v1/sites/{id}/scrape?sync=true` | Lancer un scrape |
| GET | `/v1/articles?site_id=&limit=&offset=` | Articles |
| GET | `/v1/articles/{id}` | Détail article |

## Types de scraper

- **gartner** — sélecteurs orientés gartner.com (fallback générique)
- **generic** — liens d’articles détectés par heuristiques URL + titres

> Note : certains sites (dont Gartner) peuvent bloquer les requêtes HTTP simples. Pour la prod, prévoir Playwright headless dans un profil Docker séparé.

## Intégration tgm-deploy (plus tard)

Ajouter un service `site-scraper` dans `docker-compose.prod.yml` (port 3020) et un snippet nginx `/site-scraper-api/`.

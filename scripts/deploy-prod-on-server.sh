#!/usr/bin/env bash
# À exécuter SUR LE SERVEUR (utilisateur debian, ex. SSH OVH).
# Met à jour le clone site-scraper et rebuild le conteneur Docker.
#
# Usage :
#   bash scripts/deploy-prod-on-server.sh
#   # ou depuis n'importe où si TGM_DEPLOY=/home/debian/tgm-deploy :
#   TGM_DEPLOY=/home/debian/tgm-deploy bash scripts/deploy-prod-on-server.sh

set -euo pipefail

TGM_DEPLOY="${TGM_DEPLOY:-/home/debian/tgm-deploy}"
SS_DIR="$(cd "$TGM_DEPLOY/../site-scraper" && pwd)"
COMPOSE=(docker compose -f "$TGM_DEPLOY/docker-compose.prod.yml")
if [ -f "$TGM_DEPLOY/../.env" ]; then
  COMPOSE=(docker compose --env-file "$TGM_DEPLOY/../.env" -f "$TGM_DEPLOY/docker-compose.prod.yml")
fi

echo "=== Deploy site-scraper ==="
echo "tgm-deploy : $TGM_DEPLOY"
echo "site-scraper : $SS_DIR"

if [ ! -d "$SS_DIR/.git" ]; then
  echo "Erreur: clone git absent à $SS_DIR"
  echo "  git clone git@github.com:ayaponcho/site-scraper.git $SS_DIR"
  exit 1
fi

echo "→ git pull site-scraper"
cd "$SS_DIR"
git fetch origin
git checkout main 2>/dev/null || git checkout master
git reset --hard origin/main 2>/dev/null || git reset --hard origin/master
echo "   commit: $(git log -1 --oneline)"

if [ ! -f "$SS_DIR/app/scrapers/analyze.py" ]; then
  echo "Erreur: analyze.py absent — le clone n'est pas à jour (attendu commit add scraper detail)."
  exit 1
fi

echo "→ docker build + up site-scraper"
cd "$TGM_DEPLOY"
"${COMPOSE[@]}" build --no-cache site-scraper
"${COMPOSE[@]}" up -d site-scraper

echo "→ healthcheck"
sleep 5
HEALTH=$("${COMPOSE[@]}" exec -T site-scraper python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read().decode())" 2>/dev/null || true)
echo "$HEALTH"

if echo "$HEALTH" | grep -qE '"version":"0\.2\.[0-9]+"'; then
  echo "✓ site-scraper 0.2.x — route POST /v1/analyze-url/audit disponible"
elif echo "$HEALTH" | grep -q '"version"'; then
  echo "⚠ version obsolète ($HEALTH) — attendu 0.2.0+ pour l'audit landing"
  echo "  docker logs tgm-deploy-site-scraper --tail 50"
  exit 1
else
  echo "⚠ health invalide — vérifier les logs: docker logs tgm-deploy-site-scraper --tail 50"
  exit 1
fi

echo "→ reload nginx"
docker exec nginx nginx -s reload 2>/dev/null || true
echo "=== Terminé ==="

# Déclenchement auto prod
#
# Chaque push sur `main` lance `.github/workflows/deploy-ssh.yml` :
#   CI (compileall + docker build) → SSH serveur → git pull site-scraper → docker compose up site-scraper
#
# Secrets à configurer sur https://github.com/ayaponcho/site-scraper/settings/secrets/actions
# (mêmes valeurs que emailBackend / haystack) :
#
#   SSH_HOST        — IP ou hostname du serveur (ex. neomail-back / OVH)
#   SSH_USER        — debian
#   SSH_PRIVATE_KEY — clé privée OpenSSH (PEM) autorisée sur le serveur
#   DEPLOY_PATH     — chemin ABSOLU de tgm-deploy (ex. /home/debian/tgm-deploy)
#
# Optionnel : SSH_PORT (22 par défaut)
#
# Test manuel : GitHub → Actions → Deploy site-scraper → Run workflow

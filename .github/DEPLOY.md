# Déclenchement auto prod

Chaque push sur `main` lance `.github/workflows/deploy-ssh.yml` :

CI (compileall + docker build) → SSH serveur → git pull site-scraper → docker compose up site-scraper

## Secrets GitHub

Configurer sur https://github.com/ayaponcho/site-scraper/settings/secrets/actions

| Secret | Description |
|--------|-------------|
| `SSH_HOST` | IP ou hostname du serveur (ex. neomail-back / OVH) |
| `SSH_USER` | `debian` |
| `SSH_PRIVATE_KEY` | Clé privée OpenSSH (PEM) autorisée sur le serveur |
| `DEPLOY_PATH` | Chemin absolu de tgm-deploy (ex. `/home/debian/tgm-deploy`) |
| `SSH_PORT` | *(optionnel)* port SSH, défaut 22 |
| `SSH_PASSPHRASE` | *(optionnel)* passphrase de la clé, **si** `SSH_PRIVATE_KEY` est protégée |

## Erreur SSH fréquente : clé avec passphrase

```
ssh.ParsePrivateKey: ssh: this private key is passphrase protected
ssh: handshake failed: ssh: unable to authenticate
```

**Cause :** le secret `SSH_PRIVATE_KEY` contient une clé protégée par passphrase, mais GitHub Actions ne peut pas l’utiliser sans `SSH_PASSPHRASE`.

**Solutions (choisir une) :**

### Option A — Ajouter le secret passphrase (rapide)

1. GitHub → site-scraper → Settings → Secrets → Actions
2. New secret : `SSH_PASSPHRASE` = passphrase de la clé
3. Re-lancer le workflow **Deploy site-scraper**

Le workflow lit déjà `passphrase: ${{ secrets.SSH_PASSPHRASE }}`.

### Option B — Clé de déploiement dédiée sans passphrase (recommandé prod)

Sur votre machine :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/tgm_deploy_site_scraper -N "" -C "github-actions-site-scraper"
```

Sur le serveur (en tant que `debian`) :

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "CONTENU_DE_tgm_deploy_site_scraper.pub" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Sur GitHub :

1. Mettre à jour `SSH_PRIVATE_KEY` avec le contenu de `tgm_deploy_site_scraper` (clé **privée**, sans passphrase)
2. Supprimer `SSH_PASSPHRASE` si plus utilisé

## Vérifier le déploiement

Après deploy réussi :

```bash
curl -s https://email.targetmania.com/site-scraper-api/health
# Attendu : {"status":"ok","database":true,"version":"0.1.5"}

curl -s -X POST "https://email.targetmania.com/site-scraper-api/v1/articles/1/analyze"
# 404 "Article introuvable" = route OK (article id 1 absent)
# 404 "Not Found" sans detail article = ancienne version encore active
```

## Dev local

Si **Analyser la page** renvoie `Not Found` en local :

```bash
cd docker/site-scraper
docker compose up --build -d site-scraper
curl -s http://127.0.0.1:3020/health
# doit inclure "version":"0.1.5"
```

Test manuel : GitHub → Actions → Deploy site-scraper → Run workflow

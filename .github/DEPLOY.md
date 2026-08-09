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
| `SSH_PASSPHRASE` | *(optionnel)* alias de `SSH_KEY_PASSPHRASE` |
| `SSH_KEY_PASSPHRASE` | *(optionnel)* passphrase de la clé — **sans espace ni retour ligne en trop** |

## Erreur SSH fréquente : clé avec passphrase

```
ssh.ParsePrivateKey: ssh: this private key is passphrase protected
ssh: handshake failed: ssh: unable to authenticate
```

**Cause :** le secret passphrase est absent, incorrect, ou le workflow utilisé ne déchiffre pas la clé (le paramètre `passphrase:` de appleboy/ssh-action est peu fiable).

**Solutions (choisir une) :**

### Option A — Passphrase via secret (rapide)

1. GitHub → site-scraper → Settings → Secrets → Actions
2. Secret `SSH_KEY_PASSPHRASE` (ou `SSH_PASSPHRASE`) = passphrase **exacte** de la clé
   - pas d’espace avant/après
   - pas de retour ligne en fin de valeur
3. **Pousser le dernier commit** sur `main` (le workflow déchiffre la clé avec `ssh-keygen -p`)
4. Lancer **Run workflow** (pas seulement « Re-run » sur un ancien job — voir ci-dessous)

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
2. Supprimer `SSH_PASSPHRASE` / `SSH_KEY_PASSPHRASE` si plus utilisés

## Re-run vs nouveau workflow

| Action | Comportement |
|--------|--------------|
| **Re-run failed jobs** sur un run ancien | Réutilise le **YAML du commit d’origine** — sans correctif SSH récent |
| **Run workflow** (workflow_dispatch) après push sur `main` | Utilise le **dernier YAML** sur `main` |

Si tu as ajouté `SSH_PASSPHRASE` mais le commit `fix deploy` n’était pas encore sur `origin/main`, le re-run ne pouvait pas marcher.

## Vérifier le déploiement

Après deploy réussi :

```bash
curl -s https://email.targetmania.com/site-scraper-api/health
# Attendu : {"status":"ok","database":true,"version":"0.3.0"}
# Si "version":"0.2.0" → image sans RSS (POST sites type rss → 422)
```

## Deploy manuel (si GitHub Actions bloqué)

**Depuis ta machine** (SSH vers le serveur) :

```bash
ssh debian@TON_SERVEUR
cd /home/debian/site-scraper
git pull origin main
bash scripts/deploy-prod-on-server.sh
```

Ou commandes une par une :

```bash
cd /home/debian/site-scraper
git fetch origin && git reset --hard origin/main
cd /home/debian/tgm-deploy
docker compose -f docker-compose.prod.yml build --no-cache site-scraper
docker compose -f docker-compose.prod.yml up -d site-scraper
docker exec tgm-deploy-site-scraper wget -qO- http://127.0.0.1:8080/health
# doit afficher "version":"0.2.0"
docker exec nginx nginx -s reload 2>/dev/null || true
```

**Vérification depuis ton PC** :

```bash
curl -s https://email.targetmania.com/site-scraper-api/health
# {"status":"ok","database":true,"version":"0.2.0"}
```

## Dev local

Si **Analyser la page** renvoie `Not Found` en local :

```bash
cd docker/site-scraper
docker compose up --build -d site-scraper
curl -s http://127.0.0.1:3020/health
# doit inclure "version":"0.2.0"
```

Test manuel : GitHub → Actions → Deploy site-scraper → Run workflow

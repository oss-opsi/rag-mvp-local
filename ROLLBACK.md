# Procédure de rollback — Tell me

## Tag de référence

**`v0.9.0-mvp`** — commit `b1bd582`
État stable du MVP au 26 avril 2026, avant migration Next.js + intégration sources publiques.

URL GitHub : https://github.com/oss-opsi/rag-mvp-local/releases/tag/v0.9.0-mvp

## Que contient ce tag

- Backend FastAPI (`:8000`)
- Frontend Streamlit (`:8501`)
- Qdrant (`:6333`) avec collections `cdc_client` + `knowledge_base`
- Pipeline v3.9.1 : HyDE + re-pass + bge-m3 + reranker v2-m3
- LLM OpenAI GPT-4o-mini (clé fournie au runtime)
- Authentification simple : daniel / opsidium2026
- Mono-utilisateur

## Rollback côté code (sur le VPS)

```bash
# SSH vers le VPS
ssh -i /home/user/.ssh_rag/id_ed25519 -o StrictHostKeyChecking=no root@178.238.230.178

# Aller dans le repo déployé
cd /opt/rag-mvp-local   # ou le chemin réel sur le VPS

# Sauvegarder l'état courant au cas où
git branch backup-avant-rollback-$(date +%Y%m%d-%H%M%S)

# Revenir au tag stable
git fetch --tags
git checkout v0.9.0-mvp

# Réinstaller les dépendances figées à ce tag
pip install -r requirements.txt

# Redémarrer les services
systemctl restart tellme-backend
systemctl restart tellme-streamlit
# (ou les noms réels des unités systemd)
```

## Rollback côté données (Qdrant + SQLite)

Avant de démarrer le développement v1.0, **faire un snapshot** :

```bash
# Sur le VPS
cd /opt/backups
mkdir mvp-v0.9.0-$(date +%Y%m%d)
cd mvp-v0.9.0-$(date +%Y%m%d)

# Snapshot Qdrant
curl -X POST http://localhost:6333/collections/cdc_client/snapshots
curl -X POST http://localhost:6333/collections/knowledge_base/snapshots
# Récupérer les fichiers .snapshot dans /qdrant/storage/snapshots/

# Backup SQLite
cp /opt/rag-mvp-local/data/app.db ./app.db.backup

# Backup config / .env
cp /opt/rag-mvp-local/.env ./env.backup
```

Pour restaurer en cas de problème :

```bash
# Restaurer Qdrant via API
curl -X PUT 'http://localhost:6333/collections/cdc_client/snapshots/upload' \
  -H 'Content-Type:multipart/form-data' \
  -F 'snapshot=@cdc_client-XXX.snapshot'

# Restaurer SQLite
systemctl stop tellme-backend
cp ./app.db.backup /opt/rag-mvp-local/data/app.db
systemctl start tellme-backend
```

## Stratégie de développement v1.0

Pour limiter le risque pendant le développement :

1. **Branche dédiée** : `git checkout -b v1.0-nextjs` à partir de `main` — la migration ne touche pas la branche `main` tant que la v1.0 n'est pas validée
2. **Déploiement parallèle** : la v1.0 tourne sur un nouveau port (`:3000` Next.js) en parallèle du MVP existant (`:8501` Streamlit). Les deux cohabitent jusqu'à validation.
3. **Bascule progressive** : l'utilisateur teste la v1.0 sur `:3000` ; si ça casse, le MVP reste accessible sur `:8501`.
4. **Tag à chaque étape clé** : `v1.0-alpha`, `v1.0-beta`, `v1.0` pour pouvoir revenir à un état intermédiaire.

## Contact / responsable

Daniel Jabert — daniel.jabert@opsidium.com

# Procédure de rollback — Tell me

## Tag de référence

**`v3.9.0-stable`** — commit `b1bd582`
État stable de Tell me au 26 avril 2026, avant les chantiers v4 (sources publiques + bibliothèque + référentiel).

URL GitHub : https://github.com/oss-opsi/rag-mvp-local/releases/tag/v3.9.0-stable

## Que contient ce tag

- Backend FastAPI v3.1.0 (`:8000`)
- Frontend Next.js 15 (`:3000`, mappé sur `:8501` host)
- Qdrant 1.11 (`:6333`) avec collections per-user `rag_<user_id>`
- Pipeline v3.9.0 : HyDE + re-pass + bge-m3 + reranker v2-m3 + chunker sémantique v2
- LLM OpenAI GPT-4o-mini (clé saisie par l'utilisateur, chiffrée Fernet)
- Auth JWT, multi-utilisateurs avec rôles admin/user
- 7 pages : Login, Indexation, Chat, Analyse, RAGAS, Settings, Users

## Rollback côté code (sur le VPS, déploiement Docker)

```bash
# SSH vers le VPS
ssh -i /home/user/.ssh_rag/id_ed25519 -o StrictHostKeyChecking=no root@178.238.230.178

# Aller dans le repo déployé
cd /opt/rag-mvp-local

# Sauvegarder l'état courant au cas où
git branch backup-avant-rollback-$(date +%Y%m%d-%H%M%S)

# Revenir au tag stable
git fetch --tags
git checkout v3.9.0-stable

# Reconstruire et redémarrer les conteneurs
docker compose down
docker compose up -d --build

# Vérifier la santé
curl -s http://localhost:8000/health
```

## Backup avant chantier

À faire **avant** d'entamer un chantier risqué (refactor, migration, nouvelle source) :

```bash
# Sur le VPS
mkdir -p /opt/backups/$(date +%Y%m%d)
cd /opt/backups/$(date +%Y%m%d)

# Snapshot des collections Qdrant per-user (lister puis snapshoter chacune)
curl -s http://localhost:6333/collections | jq -r '.result.collections[].name' | \
  while read col; do
    curl -X POST "http://localhost:6333/collections/$col/snapshots"
  done
# Les fichiers .snapshot sont produits dans le volume Docker qdrant_storage
docker cp rag_qdrant:/qdrant/storage/snapshots ./qdrant_snapshots

# Backup des bases SQLite (volume backend_data)
docker cp rag_backend:/data ./backend_data_backup

# Backup .env
cp /opt/rag-mvp-local/.env ./env.backup
```

## Restauration des données

```bash
# Restaurer une collection Qdrant
curl -X PUT "http://localhost:6333/collections/<nom>/snapshots/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "snapshot=@./qdrant_snapshots/<fichier>.snapshot"

# Restaurer les SQLite
docker compose stop backend
docker cp ./backend_data_backup/. rag_backend:/data
docker compose start backend
```

## Stratégie de développement pour les chantiers à venir

Pour limiter le risque :

1. **Branche dédiée** par chantier : `git checkout -b chore/cleanup-streamlit`, `feat/connector-legifrance`, etc. — `main` reste sur le tag stable jusqu'à validation
2. **Tag intermédiaire** à chaque étape clé : `v3.9.1-cleanup`, `v3.10.0-legifrance`, `v3.11.0-boss`, etc.
3. **Tests manuels** avant merge sur `main` (au minimum : login, upload, chat, analyse CDC sur un CDC connu)
4. **Rollback en 1 commande** : `git checkout v3.9.0-stable && docker compose up -d --build`

## Contact / responsable

Daniel Jabert — daniel.jabert@opsidium.com

# Déploiement du backend RAG MVP sur Render.com

Ce guide décrit comment déployer le backend FastAPI sur [Render.com](https://render.com) avec une base vectorielle Qdrant.

---

## Prérequis

- Compte [Render.com](https://render.com) (tier gratuit suffisant pour l'Option A)
- Repository GitHub connecté : [github.com/oss-opsi/rag-mvp-local](https://github.com/oss-opsi/rag-mvp-local)
- Clé API OpenAI (saisie dans le frontend Streamlit, non stockée côté serveur)

---

## Option A — Recommandée pour la démo : Backend Render Free + Qdrant Cloud Free

Cette option utilise le **tier gratuit de Render** pour le backend et le **tier gratuit de Qdrant Cloud** (1 Go de stockage) pour la base vectorielle. Aucune carte bancaire requise.

### Étape 1 — Créer un cluster Qdrant Cloud gratuit

1. Rendez-vous sur [cloud.qdrant.io](https://cloud.qdrant.io) et créez un compte.
2. Cliquez sur **Create Cluster** → choisissez **Free tier** (1 Go, 1 vCPU).
3. Sélectionnez la région la plus proche (ex. `eu-west` pour l'Europe).
4. Une fois le cluster créé, notez :
   - **Cluster URL** : de la forme `https://xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.europe-west3-0.gcp.cloud.qdrant.io:6333`
   - **API Key** : générée dans l'onglet *API Keys* du cluster (cliquez **Create**).

### Étape 2 — Déployer le backend sur Render

1. Connectez-vous à [dashboard.render.com](https://dashboard.render.com).
2. Cliquez sur **New → Web Service**.
3. Connectez votre compte GitHub si ce n'est pas déjà fait.
4. Sélectionnez le repository **`oss-opsi/rag-mvp-local`**.
5. Renseignez les paramètres suivants :

   | Champ | Valeur |
   |-------|--------|
   | **Name** | `rag-mvp-backend` |
   | **Region** | `Frankfurt (EU Central)` ou selon préférence |
   | **Branch** | `main` |
   | **Root Directory** | *(laisser vide — le Dockerfile est dans `./backend/`)* |
   | **Runtime** | `Docker` |
   | **Dockerfile Path** | `./backend/Dockerfile` |
   | **Docker Context** | `./backend` |
   | **Instance Type** | `Free` |

6. Dans la section **Environment Variables**, ajoutez :

   | Clé | Valeur |
   |-----|--------|
   | `QDRANT_URL` | `https://<votre-cluster>.cloud.qdrant.io:6333` *(Cluster URL de l'étape 1)* |
   | `QDRANT_API_KEY` | `<votre-api-key>` *(API Key de l'étape 1)* |
   | `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
   | `COLLECTION_NAME` | `rag_docs` |

7. Cliquez sur **Create Web Service**.
8. Attendez la fin du build (5–10 min la première fois — le modèle d'embeddings est téléchargé à la construction).

### Étape 3 — Vérifier le déploiement

Une fois le déploiement terminé, notez l'URL publique du service, de la forme :
```
https://rag-mvp-backend-xxxx.onrender.com
```

Testez l'endpoint de santé :
```bash
curl https://rag-mvp-backend-xxxx.onrender.com/health
# Réponse attendue : {"status":"ok","indexed_vectors":0,"qdrant_url":"https://..."}
```

### Étape 4 — Connecter le frontend Streamlit

Sur [Streamlit Community Cloud](https://streamlit.io/cloud) :

1. Ouvrez les **Settings** de votre app Streamlit.
2. Dans la section **Secrets** ou **Environment Variables**, ajoutez :
   ```
   BACKEND_URL=https://rag-mvp-backend-xxxx.onrender.com
   ```
3. Redémarrez l'app Streamlit.

---

## Option B — Render Blueprint (déploiement groupé via `render.yaml`)

Le fichier `render.yaml` à la racine du repo permet un déploiement en un clic.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/oss-opsi/rag-mvp-local)

> **Important** : Le service Qdrant privé (`type: pserv`) requiert un **plan payant Render** (Starter, ~7 $/mois). Sur le tier gratuit, seul le backend Web Service peut être déployé via Blueprint — utilisez Qdrant Cloud pour la base vectorielle (Option A).

### Déploiement Blueprint pas à pas

1. Cliquez sur le bouton **Deploy to Render** ci-dessus.
2. Connectez votre compte GitHub.
3. Render détecte `render.yaml` et vous propose de créer les services définis.
4. Renseignez les variables d'environnement demandées (`QDRANT_URL`, `QDRANT_API_KEY`).
5. Cliquez sur **Apply** pour lancer le déploiement.

---

## Limitations du tier gratuit Render

| Contrainte | Détail |
|------------|--------|
| **Mise en veille** | Le service s'endort après **15 minutes d'inactivité**. La première requête après la mise en veille prend ~30 s (cold start). Acceptable pour une démo. |
| **RAM** | **512 Mo** maximum. Le modèle d'embeddings (`BAAI/bge-small-en-v1.5`) occupe ~400 Mo. Cela fonctionne, mais la marge est faible. |
| **Disque** | **Aucun disque persistant** sur le tier gratuit. Le corpus BM25 (stocké dans `/tmp/`) est perdu au redémarrage, mais les vecteurs Qdrant Cloud survivent. |
| **Services privés** | `type: pserv` (Qdrant auto-hébergé dans Render) n'est **pas disponible** sur le tier gratuit → utiliser Qdrant Cloud (Option A). |
| **Durée de build** | Le build télécharge ~400 Mo de modèle HuggingFace → prévoir 5–10 min. |

---

## Dépannage

### Le build échoue avec OOM (Out Of Memory)
- Le modèle est téléchargé **pendant le build** (pas au runtime) — cela demande de la RAM build-time.
- Solution : passer au plan **Starter** ($7/mo) ou utiliser un modèle d'embeddings plus léger.

### 502 Bad Gateway sur la première requête
- Normal après une mise en veille. Attendez ~30 secondes et réessayez.
- Le message Render "Service unavailable" apparaît pendant le cold start.

### Erreur CORS
- Le backend autorise déjà toutes les origines (`allow_origins=["*"]`). Si vous voyez une erreur CORS, vérifiez que `BACKEND_URL` dans le frontend pointe bien vers `https://` (pas `http://`).

### Qdrant retourne 401 Unauthorized
- Vérifiez que `QDRANT_API_KEY` est correctement renseigné dans les variables d'environnement Render.
- L'API key Qdrant Cloud est **sensible à la casse** — copiez-la directement depuis le dashboard Qdrant.

### Les documents indexés disparaissent après redéploiement
- Sur Render free tier, les fichiers `/tmp/` sont perdus à chaque redéploiement.
- Les **vecteurs dans Qdrant Cloud** sont persistants (non affectés par les redéploiements du backend).
- Le **corpus BM25** (en mémoire + `/tmp/bm25_corpus.pkl`) est perdu : re-uploadez vos documents après chaque redéploiement, ou implémentez une reconstruction BM25 depuis Qdrant au démarrage.

---

## Récapitulatif des URLs et variables

| Variable | Description | Exemple |
|----------|-------------|---------|
| `QDRANT_URL` | URL du cluster Qdrant Cloud | `https://abc123.cloud.qdrant.io:6333` |
| `QDRANT_API_KEY` | Clé API Qdrant Cloud | `sk-qdrant-xxxxxxxx` |
| `EMBEDDING_MODEL` | Modèle d'embeddings HuggingFace | `BAAI/bge-small-en-v1.5` |
| `COLLECTION_NAME` | Nom de la collection Qdrant | `rag_docs` |
| Backend URL (Render) | URL publique du backend | `https://rag-mvp-backend-xxxx.onrender.com` |

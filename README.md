# RAG MVP — Recherche Documentaire Hybride

## Nouveautés v3.1 — Mode Docker parité complète avec le mode autonome

Les fonctionnalités v3 (auth JWT, historique des conversations, évaluation RAGAS) sont désormais disponibles **dans les deux modes** : Docker split (FastAPI + Streamlit) et mode autonome (`streamlit_app.py`).

| # | Fonctionnalité | Mode Docker | Mode Autonome |
|---|---|---|---|
| 1 | **Auth JWT** | ✅ Login / Inscription / Invité via `/auth/*` | ✅ streamlit-authenticator |
| 2 | **Index par utilisateur** | ✅ Collection `rag_<user_id>` dans Qdrant persistant | ✅ Collection en mémoire |
| 3 | **Historique SQLite** | ✅ Persistant dans volume Docker `/data/conversations.db` | ✅ Persistant dans `./data/` |
| 4 | **Évaluation RAGAS** | ✅ Endpoint `/evaluate` (CSV upload) | ✅ Onglet dédié |
| 5 | **Token cookie** | ✅ extra-streamlit-components CookieManager | — |

### Architecture multi-utilisateurs (mode Docker)

Chaque utilisateur authentifié possède :
- Sa propre **collection Qdrant** : `rag_<user_id>` (ex: `rag_alice`)
- Son propre **corpus BM25** persisté dans `/data/bm25/<user_id>.pkl`
- Son propre **historique de conversations** filtré par `user_id` en SQLite

Le token JWT (HS256, 7 jours) est émis par le backend à la connexion et vérifié sur chaque requête protégée via un header `Authorization: Bearer <token>`.

### Variable d'environnement JWT_SECRET

⚠️ **Changez impérativement `JWT_SECRET` en production** :

```bash
# Générer une valeur forte :
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Dans votre .env :
JWT_SECRET=<valeur_générée>
```

---

## Nouveautés v3 Phase A

| # | Fonctionnalité | Détail |
|---|---|---|
| 1 | **Évaluation RAGAS** | Onglet dédié `📊 Évaluation RAGAS` : uploadez un CSV `question,ground_truth`, lancez l'évaluation et obtenez les scores RAGAS (faithfulness, answer_relevancy, context_precision, context_recall) avec indicateurs visuels colorés et export CSV. |
| 2 | **Historique des conversations (SQLite)** | Onglet `🗂️ Historique` : toutes vos conversations sont persistées en SQLite (`./data/conversations.db`). Vous pouvez les consulter, les exporter en JSON ou les supprimer. Chaque échange est horodaté. |
| 3 | **Authentification multi-utilisateurs** | Système de login/inscription. Chaque utilisateur a son propre index Qdrant isolé (`rag_<username>`). **Mode invité** disponible sur l'écran de connexion. |

---

## Nouveautés v2

| # | Amélioration | Détail |
|---|---|---|
| 1 | **Mode mémoire (clean-session)** | `streamlit_app.py` utilise `QdrantClient(":memory:")` : l'index Qdrant et le corpus BM25 sont entièrement en mémoire et réinitialisés à chaque redémarrage. |
| 2 | **Réponses en streaming (token par token)** | Le LLM génère les réponses en flux continu via `chain.stream(...)`. Dans `streamlit_app.py` et `frontend/app.py`, `st.write_stream(...)` affiche les tokens au fur et à mesure. Le backend FastAPI expose un endpoint `POST /query/stream` (Server-Sent Events). |
| 3 | **Cross-encoder reranker** | Un reranker `CrossEncoderReranker` basé sur `BAAI/bge-reranker-base` est disponible en option. Activé via une case à cocher dans la barre latérale. |
| 4 | **Support DOCX, TXT, Markdown** | L'indexation accepte `.pdf`, `.docx`, `.txt` et `.md`. |

---

## Description du projet

RAG MVP est une application de **Retrieval-Augmented Generation** (RAG) locale et complète. Elle permet d'indexer des documents (PDF, DOCX, TXT, MD) et de poser des questions en langage naturel, en obtenant des réponses sourcées générées par GPT-4o-mini.

L'application implémente une **recherche hybride** combinant :
- **Recherche dense** (embeddings BAAI/bge-small-en-v1.5 dans Qdrant)
- **Recherche sparse** (BM25 via rank-bm25)
- **Fusion RRF** (Reciprocal Rank Fusion) — 100 % mathématique, sans modèle de reranking lourd

Deux modes de déploiement sont disponibles depuis la même base de code :

| Mode | Description |
|------|-------------|
| **Docker Compose** | Streamlit + FastAPI + Qdrant dans des conteneurs séparés — persistance complète, multi-utilisateurs, auth JWT |
| **Autonome** | Un seul fichier `streamlit_app.py` avec Qdrant en mémoire |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Mode Docker Compose (v3.1)                    │
│                                                                  │
│   ┌──────────────┐    HTTP/JWT  ┌─────────────────┐             │
│   │  Streamlit   │ ──────────►  │   FastAPI         │             │
│   │  :8501       │             │   Backend :8000   │             │
│   │  (frontend)  │             │                   │             │
│   └──────────────┘             │  /auth/*  (JWT)   │             │
│                                │  /upload          │             │
│                                │  /query/stream    │             │
│                                │  /conversations   │             │
│                                │  /evaluate        │             │
│                                └────────┬──────────┘             │
│                                         │                        │
│                            ┌────────────┼────────────┐          │
│                            ▼            ▼            ▼          │
│                    ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│                    │  Qdrant  │  │ users.db │  │conversations│  │
│                    │  :6333   │  │ (SQLite) │  │ .db       │   │
│                    │  /data/  │  │ /data/   │  │ /data/    │   │
│                    └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        Mode Autonome (v3)                        │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │                  streamlit_app.py                         │  │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐  │  │
│   │  │  Ingest    │  │  Retriever │  │   LangChain Chain  │  │  │
│   │  │  (PDF→HF)  │  │  BM25+RRF │  │   GPT-4o-mini      │  │  │
│   │  └────────────┘  └────────────┘  └────────────────────┘  │  │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐  │  │
│   │  │  Auth      │  │  History   │  │   RAGAS Eval       │  │  │
│   │  │  (SQLite)  │  │  (SQLite)  │  │   (datasets)       │  │  │
│   │  └────────────┘  └────────────┘  └────────────────────┘  │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prérequis

- **Docker** ≥ 24 et **Docker Compose** ≥ 2.20 (mode Docker)
- **Python** ≥ 3.11 (mode autonome)
- **Clé API OpenAI** (saisie dans l'interface, jamais stockée)

---

## Installation rapide (mode Docker)

```bash
# 1. Cloner le projet
git clone https://github.com/oss-opsi/rag-mvp-local rag-mvp
cd rag-mvp

# 2. Configurer les variables d'environnement (IMPORTANT en production)
cp .env.example .env
# Éditez .env et changez JWT_SECRET !
# python -c "import secrets; print(secrets.token_urlsafe(48))"

# 3. Construire et démarrer tous les services
docker compose up --build -d
```

La première exécution télécharge le modèle d'embeddings (~130 Mo) — prévoir quelques minutes.

---

## Déploiement sur VPS (mise à jour)

```bash
cd /opt/rag-mvp-local
git pull
docker compose up -d --build
```

---

## Accès aux services

| Service | URL |
|---------|-----|
| Interface Streamlit | http://localhost:8501 |
| API FastAPI (Swagger) | http://localhost:8000/docs |
| Tableau de bord Qdrant | http://localhost:6333/dashboard |

---

## Mode autonome (sans Docker)

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Lancer l'application
streamlit run streamlit_app.py
```

En mode autonome, Qdrant et le corpus BM25 sont entièrement **en mémoire** : l'index est réinitialisé à chaque redémarrage. Les données utilisateurs et l'historique des conversations sont persistées dans `./data/` (SQLite).

---

## Usage

### 1. Connexion / Mode invité (v3)
Sur l'écran d'accueil, vous pouvez :
- **Se connecter** avec un compte existant
- **S'inscrire** pour créer un compte (onglet Inscription)
- **Mode invité** : accès direct sans compte. *L'index invité est partagé entre tous les visiteurs en mode invité.*

### 2. Renseigner la clé OpenAI
Dans la barre latérale gauche, entrez votre clé API OpenAI (`sk-...`). Elle est transmise directement à l'API OpenAI sans être stockée.

### 3. Indexer un document
1. Glissez-déposez un ou plusieurs fichiers PDF, DOCX, TXT ou MD
2. Cliquez sur **Indexer les documents**
3. Attendez la confirmation (nombre de fragments indexés)

### 4. Poser une question (onglet 💬 Chat)
Tapez votre question dans le champ de saisie. L'assistant recherche les passages pertinents et génère une réponse sourcée en streaming.

### 5. Évaluation RAGAS (onglet 📊 Évaluation RAGAS)
1. Préparez un CSV avec les colonnes `question` et `ground_truth` (max 20 lignes)
2. Uploadez-le dans l'onglet Évaluation
3. Cliquez sur **Lancer l'évaluation**
4. Consultez les scores et exportez les résultats

### 6. Historique (onglet 🗂️ Historique)
- Toutes vos conversations sont sauvegardées automatiquement (mode Docker, utilisateurs connectés)
- Cliquez sur une conversation pour la relire, la renommer, l'exporter ou la supprimer

---

## Variables d'environnement

| Variable | Valeur par défaut | Description |
|----------|------------------|-------------|
| `JWT_SECRET` | *(valeur dev insécurisée)* | **⚠️ CHANGER EN PRODUCTION** — Secret de signature JWT |
| `QDRANT_URL` | `http://qdrant:6333` | URL du serveur Qdrant |
| `QDRANT_COLLECTION` | `rag_documents` | Nom de collection par défaut |
| `LLM_MODEL` | `gpt-4o-mini` | Modèle OpenAI |
| `LLM_TEMPERATURE` | `0.1` | Température du LLM |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Modèle d'embeddings |
| `DATA_DIR` | `/data` | Répertoire des données (SQLite, BM25) |
| `CHUNK_SIZE` | `800` | Taille des fragments (caractères) |
| `CHUNK_OVERLAP` | `120` | Chevauchement des fragments |
| `RETRIEVAL_K` | `5` | Nombre de résultats finaux |
| `BACKEND_URL` | `http://backend:8000` | URL backend (frontend Docker) |

> **Important** : La clé API OpenAI n'est **jamais** stockée dans les variables d'environnement. Elle est saisie par l'utilisateur dans l'interface Streamlit.

---

## Structure du projet

```
rag-mvp/
├── README.md                    # Ce fichier
├── docker-compose.yml           # Orchestration Docker
├── .env.example                 # Variables d'environnement (exemple)
├── requirements.txt             # Dépendances (mode autonome)
├── streamlit_app.py             # Application autonome v3 (auth + RAGAS + historique)
├── data/                        # SQLite databases (éphémère, non versionné)
├── backend/
│   ├── Dockerfile
│   ├── main.py                  # API FastAPI v3.1 (auth JWT + history + RAGAS)
│   ├── requirements.txt
│   └── rag/
│       ├── __init__.py
│       ├── config.py            # Configuration (JWT, DATA_DIR, BM25_DIR, etc.)
│       ├── jwt_utils.py         # [v3.1] JWT create/decode
│       ├── ingest.py            # Ingestion par utilisateur (collection + BM25 per-user)
│       ├── retriever.py         # Recherche hybride + RRF (+ factory per-user)
│       ├── reranker.py          # Cross-encoder reranker
│       ├── chain.py             # Chaîne LangChain + streaming (per-user)
│       ├── evaluation.py        # Évaluation RAGAS
│       ├── history.py           # Historique SQLite des conversations
│       └── auth.py              # Authentification (SQLite + bcrypt + JWT re-export)
└── frontend/
    ├── Dockerfile
    ├── app.py                   # Interface Streamlit v3.1 (auth + history + RAGAS)
    └── requirements.txt
```

---

## Arrêter les services

```bash
# Arrêter les conteneurs
docker compose down

# Arrêter et effacer les données (volumes)
docker compose down -v
```

---

## Technologies utilisées

- [Qdrant](https://qdrant.tech/) v1.11 — base de données vectorielle persistante
- [LangChain](https://python.langchain.com/) — chaîne RAG (LCEL)
- [HuggingFace / sentence-transformers](https://huggingface.co/) — modèle d'embeddings
- [rank-bm25](https://github.com/dorianbrown/rank_bm25) — recherche BM25
- [RAGAS](https://docs.ragas.io/) — framework d'évaluation RAG
- [PyJWT](https://pyjwt.readthedocs.io/) — tokens JWT HS256
- [bcrypt](https://pypi.org/project/bcrypt/) — hachage de mots de passe
- [FastAPI](https://fastapi.tiangolo.com/) — API REST backend
- [Streamlit](https://streamlit.io/) — interface utilisateur
- [extra-streamlit-components](https://github.com/nicedouble/StreamlitAntdComponents) — CookieManager
- [pypdf](https://pypdf.readthedocs.io/) — lecture de fichiers PDF
- [OpenAI GPT-4o-mini](https://openai.com/) — génération de réponses

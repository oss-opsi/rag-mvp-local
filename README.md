# RAG MVP — Recherche Documentaire Hybride

## Nouveautés v3 Phase A

| # | Fonctionnalité | Détail |
|---|---|---|
| 1 | **Évaluation RAGAS** | Onglet dédié `📊 Évaluation RAGAS` : uploadez un CSV `question,ground_truth`, lancez l'évaluation et obtenez les scores RAGAS (faithfulness, answer_relevancy, context_precision, context_recall) avec indicateurs visuels colorés et export CSV. |
| 2 | **Historique des conversations (SQLite)** | Onglet `🗂️ Historique` : toutes vos conversations sont persistées en SQLite (`./data/conversations.db`). Vous pouvez les consulter, les exporter en JSON ou les supprimer. Chaque échange est horodaté. |
| 3 | **Authentification multi-utilisateurs** | Système de login/inscription avec `streamlit-authenticator`. Chaque utilisateur a son propre index Qdrant isolé (`rag_<username>`). **Mode invité** disponible sur l'écran de connexion — index partagé avec tous les invités, peut être réinitialisé à tout moment. |

> **Note sur la persistance des données** : Les conversations et les comptes utilisateurs sont stockés dans des fichiers SQLite dans le répertoire `./data/`. Sur **Streamlit Community Cloud**, ce répertoire est **éphémère** : il est réinitialisé à chaque redéploiement de l'application. L'index Qdrant (vecteurs) est également en mémoire et se perd au redémarrage. Pour une persistance durable, un déploiement auto-hébergé est recommandé.

---

## Nouveautés v2

| # | Amélioration | Détail |
|---|---|---|
| 1 | **Mode mémoire (clean-session)** | `streamlit_app.py` utilise désormais `QdrantClient(":memory:")` : l'index Qdrant et le corpus BM25 sont entièrement en mémoire et réinitialisés à chaque redémarrage. Aucun fichier n'est écrit sur le disque. |
| 2 | **Réponses en streaming (token par token)** | Le LLM génère les réponses en flux continu via `chain.stream(...)`. Dans `streamlit_app.py` et `frontend/app.py`, `st.write_stream(...)` affiche les tokens au fur et à mesure. Le backend FastAPI expose un nouvel endpoint `POST /query/stream` (Server-Sent Events). |
| 3 | **Cross-encoder reranker** | Un reranker `CrossEncoderReranker` basé sur `BAAI/bge-reranker-base` est disponible en option (chargement différé). Activé via une case à cocher dans la barre latérale. Quand il est actif, RRF sélectionne 15 candidats, puis le cross-encoder les reclasse et retient les 5 meilleurs. Les scores RRF et rerank sont affichés dans le panneau **📚 Sources**. |
| 4 | **Support DOCX, TXT, Markdown** | L'indexation accepte désormais `.pdf`, `.docx`, `.txt` et `.md`. Le bon loader est choisi automatiquement selon l'extension. Les interfaces de dépôt de fichiers ont été mises à jour en conséquence. |

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
| **Docker Compose** | Streamlit + FastAPI + Qdrant dans des conteneurs séparés |
| **Autonome** | Un seul fichier `streamlit_app.py` avec Qdrant en mode local |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Mode Docker Compose                       │
│                                                                  │
│   ┌──────────────┐    HTTP     ┌─────────────────┐              │
│   │  Streamlit   │ ──────────► │   FastAPI        │              │
│   │  :8501       │             │   Backend :8000  │              │
│   └──────────────┘             └────────┬────────┘              │
│                                         │                        │
│                                gRPC/HTTP│                        │
│                                         ▼                        │
│                               ┌─────────────────┐               │
│                               │   Qdrant :6333   │               │
│                               │  (vectoriel DB)  │               │
│                               └─────────────────┘               │
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

Pipeline RAG :
  PDF → PyPDFLoader → RecursiveCharacterTextSplitter (800/120)
      → HuggingFaceEmbeddings (bge-small-en-v1.5, dim=384)
      → Qdrant (COSINE) + BM25 corpus  [par utilisateur]
      → Requête : Dense (top 20) + Sparse (top 20)
      → RRF Fusion → Top 5
      → ChatOpenAI (gpt-4o-mini) → Réponse sourcée
```

---

## Prérequis

- **Docker** ≥ 24 et **Docker Compose** ≥ 2.20 (mode Docker)
- **Python** ≥ 3.11 (mode autonome)
- **Clé API OpenAI** (saisie dans l'interface, jamais stockée)

---

## Installation rapide (mode Docker)

```bash
# 1. Cloner / copier le projet
git clone <url-du-repo> rag-mvp
cd rag-mvp

# 2. (Optionnel) Configurer les variables d'environnement
cp .env.example .env

# 3. Construire et démarrer tous les services
docker-compose up --build

# Pour démarrer en arrière-plan :
docker-compose up --build -d
```

La première exécution télécharge le modèle d'embeddings (~130 Mo) — prévoir quelques minutes.

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

En mode autonome, Qdrant et le corpus BM25 sont entièrement **en mémoire** : l'index est réinitialisé à chaque redémarrage (aucune donnée vectorielle persistée sur disque).

Les données utilisateurs et l'historique des conversations sont persistées dans `./data/` (SQLite). Ce répertoire est **éphémère sur Streamlit Community Cloud**.

---

## Usage

### 1. Connexion / Mode invité (v3)
Sur l'écran d'accueil, vous pouvez :
- **Se connecter** avec un compte existant
- **S'inscrire** pour créer un compte (onglet Inscription)
- **Mode invité** : cliquez sur le bouton dédié pour accéder directement sans créer de compte. *Attention : l'index invité est partagé entre tous les visiteurs en mode invité et peut être réinitialisé à tout moment.*

### 2. Renseigner la clé OpenAI
Dans la barre latérale gauche, entrez votre clé API OpenAI (`sk-...`). Elle est transmise directement à l'API OpenAI sans être stockée.

### 3. Indexer un document
1. Glissez-déposez un ou plusieurs fichiers PDF, DOCX, TXT ou MD dans la zone de dépôt
2. Cliquez sur **Indexer les documents**
3. Attendez la confirmation (nombre de fragments indexés)

### 4. Poser une question (onglet 💬 Chat)
Tapez votre question dans le champ de saisie en bas de la page. L'assistant :
1. Recherche les passages les plus pertinents (dense + BM25 + RRF)
2. Génère une réponse en français, sourcée avec `[fichier.pdf p.X]`
3. Affiche les fragments sources dans un panneau dépliable **📚 Sources**

### 5. Évaluation RAGAS (onglet 📊 Évaluation RAGAS) — v3
1. Préparez un CSV avec les colonnes `question` et `ground_truth`
2. Uploadez-le dans l'onglet Évaluation
3. Cliquez sur **Lancer l'évaluation**
4. Consultez les scores (fidélité, pertinence, précision, rappel) et exportez les résultats

### 6. Historique (onglet 🗂️ Historique) — v3
- Toutes vos conversations sont sauvegardées automatiquement
- Cliquez sur une conversation pour la relire
- Exportez n'importe quelle conversation en JSON
- Démarrez une nouvelle conversation avec le bouton **🆕 Nouvelle conversation**

---

## Explication du RRF et de la recherche hybride

### Recherche dense
Les chunks de texte sont convertis en vecteurs de dimension 384 par le modèle **BAAI/bge-small-en-v1.5** (HuggingFace). La recherche par similarité cosinus dans Qdrant identifie les 20 chunks sémantiquement les plus proches.

### Recherche sparse (BM25)
BM25 (Best Match 25) est un algorithme de pertinence lexicale qui pondère les termes selon leur fréquence dans le document (`TF`) et leur rareté dans le corpus (`IDF`). Il est efficace pour les correspondances exactes de termes techniques.

### Reciprocal Rank Fusion (RRF)

La fusion RRF combine les classements des deux listes sans avoir besoin de score absolu :

```
score_RRF(doc) = Σᵢ  1 / (k + rangᵢ)
```

où :
- `k = 60` (constante d'amortissement)
- `rangᵢ` = position du document dans la liste `i` (0-indexé)
- La somme porte sur toutes les listes où le document apparaît

Les 5 documents avec le score RRF le plus élevé constituent le contexte transmis au LLM.

---

## Structure du projet

```
rag-mvp/
├── README.md                    # Ce fichier
├── docker-compose.yml           # Orchestration Docker
├── .env.example                 # Variables d'environnement (exemple)
├── .gitignore
├── .dockerignore
├── requirements.txt             # Dépendances (mode autonome)
├── streamlit_app.py             # Application autonome v3 (auth + RAGAS + historique)
├── data/                        # SQLite databases (éphémère, non versionné)
│   ├── conversations.db         # Historique des conversations
│   └── users.db                 # Comptes utilisateurs
├── backend/
│   ├── Dockerfile
│   ├── main.py                  # API FastAPI
│   ├── requirements.txt
│   └── rag/
│       ├── __init__.py
│       ├── config.py            # Configuration centralisée
│       ├── ingest.py            # Ingestion PDF → Qdrant + BM25
│       ├── retriever.py         # Recherche hybride + fusion RRF (+ reranking)
│       ├── reranker.py          # Cross-encoder reranker (BAAI/bge-reranker-base)
│       ├── chain.py             # Chaîne LangChain (LCEL) + GPT-4o-mini + streaming
│       ├── evaluation.py        # [v3] Évaluation RAGAS
│       ├── history.py           # [v3] Historique SQLite des conversations
│       └── auth.py              # [v3] Authentification utilisateurs (SQLite + bcrypt)
└── frontend/
    ├── Dockerfile
    ├── app.py                   # Interface Streamlit (mode Docker — v2 features only)
    └── requirements.txt
```

---

## Variables d'environnement

| Variable | Valeur par défaut | Description |
|----------|------------------|-------------|
| `QDRANT_URL` | `http://qdrant:6333` | URL du serveur Qdrant |
| `QDRANT_COLLECTION` | `rag_documents` | Nom de la collection |
| `LLM_MODEL` | `gpt-4o-mini` | Modèle OpenAI |
| `LLM_TEMPERATURE` | `0.1` | Température du LLM |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Modèle d'embeddings |
| `CHUNK_SIZE` | `800` | Taille des fragments (caractères) |
| `CHUNK_OVERLAP` | `120` | Chevauchement des fragments |
| `RETRIEVAL_K` | `5` | Nombre de résultats finaux |
| `RETRIEVAL_K_DENSE` | `20` | Candidats recherche dense |
| `RETRIEVAL_K_SPARSE` | `20` | Candidats recherche BM25 |
| `RRF_K` | `60` | Constante de fusion RRF |
| `BACKEND_URL` | `http://backend:8000` | URL backend (frontend Docker) |
| `AUTH_COOKIE_KEY` | *(dev default)* | Clé secrète pour les cookies d'auth (v3) |

> **Important** : La clé API OpenAI n'est **jamais** stockée dans les variables d'environnement. Elle est saisie par l'utilisateur dans l'interface Streamlit et transmise directement aux requêtes.

---

## Arrêter les services

```bash
# Arrêter et supprimer les conteneurs
docker-compose down

# Arrêter et supprimer les conteneurs + les volumes (efface les données)
docker-compose down -v
```

---

## Déploiement sur Render

Pour déployer le backend FastAPI sur [Render.com](https://render.com), consultez le guide détaillé : **[DEPLOY_RENDER.md](./DEPLOY_RENDER.md)**.

Deux options disponibles :
- **Option A** (recommandée) — Backend Render Free + [Qdrant Cloud](https://cloud.qdrant.io) Free (1 Go, sans carte bancaire)
- **Option B** — Blueprint Render (`render.yaml`) avec Qdrant hébergé sur Render (plan payant requis pour Qdrant)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/oss-opsi/rag-mvp-local)

---

## Technologies utilisées

- [Qdrant](https://qdrant.tech/) v1.11 — base de données vectorielle
- [LangChain](https://python.langchain.com/) — chaîne RAG (LCEL)
- [HuggingFace / sentence-transformers](https://huggingface.co/) — modèle d'embeddings
- [rank-bm25](https://github.com/dorianbrown/rank_bm25) — recherche BM25
- [RAGAS](https://docs.ragas.io/) — framework d'évaluation RAG
- [streamlit-authenticator](https://github.com/mkhorasani/Streamlit-Authenticator) — authentification
- [FastAPI](https://fastapi.tiangolo.com/) — API REST backend
- [Streamlit](https://streamlit.io/) — interface utilisateur
- [pypdf](https://pypdf.readthedocs.io/) — lecture de fichiers PDF
- [OpenAI GPT-4o-mini](https://openai.com/) — génération de réponses

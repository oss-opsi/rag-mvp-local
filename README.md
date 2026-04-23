# RAG MVP — Recherche Documentaire Hybride

## Description du projet

RAG MVP est une application de **Retrieval-Augmented Generation** (RAG) locale et complète. Elle permet d'indexer des documents PDF et de poser des questions en langage naturel, en obtenant des réponses sourcées générées par GPT-4o-mini.

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
│                        Mode Autonome                             │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │                  streamlit_app.py                         │  │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐  │  │
│   │  │  Ingest    │  │  Retriever │  │   LangChain Chain  │  │  │
│   │  │  (PDF→HF)  │  │  BM25+RRF │  │   GPT-4o-mini      │  │  │
│   │  └────────────┘  └────────────┘  └────────────────────┘  │  │
│   │              ↕ Qdrant local (./qdrant_data/)              │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

Pipeline RAG :
  PDF → PyPDFLoader → RecursiveCharacterTextSplitter (800/120)
      → HuggingFaceEmbeddings (bge-small-en-v1.5, dim=384)
      → Qdrant (COSINE) + BM25 corpus
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

Les données sont persistées dans `./qdrant_data/` (Qdrant local) et `./qdrant_data/bm25_corpus.pkl` (corpus BM25).

---

## Usage

### 1. Renseigner la clé OpenAI
Dans la barre latérale gauche, entrez votre clé API OpenAI (`sk-...`). Elle est transmise directement à l'API OpenAI sans être stockée.

### 2. Indexer un PDF
1. Glissez-déposez un ou plusieurs fichiers PDF dans la zone de dépôt
2. Cliquez sur **Indexer les documents**
3. Attendez la confirmation (nombre de fragments indexés)

### 3. Poser une question
Tapez votre question dans le champ de saisie en bas de la page. L'assistant :
1. Recherche les passages les plus pertinents (dense + BM25 + RRF)
2. Génère une réponse en français, sourcée avec `[fichier.pdf p.X]`
3. Affiche les fragments sources dans un panneau dépliable **📚 Sources**

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
├── streamlit_app.py             # Application autonome (mode embedded)
├── backend/
│   ├── Dockerfile
│   ├── main.py                  # API FastAPI
│   ├── requirements.txt
│   └── rag/
│       ├── __init__.py
│       ├── config.py            # Configuration centralisée
│       ├── ingest.py            # Ingestion PDF → Qdrant + BM25
│       ├── retriever.py         # Recherche hybride + fusion RRF
│       └── chain.py             # Chaîne LangChain (LCEL) + GPT-4o-mini
└── frontend/
    ├── Dockerfile
    ├── app.py                   # Interface Streamlit (mode Docker)
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

## Technologies utilisées

- [Qdrant](https://qdrant.tech/) v1.11 — base de données vectorielle
- [LangChain](https://python.langchain.com/) — chaîne RAG (LCEL)
- [HuggingFace / sentence-transformers](https://huggingface.co/) — modèle d'embeddings
- [rank-bm25](https://github.com/dorianbrown/rank_bm25) — recherche BM25
- [FastAPI](https://fastapi.tiangolo.com/) — API REST backend
- [Streamlit](https://streamlit.io/) — interface utilisateur
- [pypdf](https://pypdf.readthedocs.io/) — lecture de fichiers PDF
- [OpenAI GPT-4o-mini](https://openai.com/) — génération de réponses

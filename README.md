# Tell me — Plateforme RAG SIRH/Paie

**Tell me** est une plateforme de Retrieval-Augmented Generation (RAG) spécialisée pour les consultants en SIRH, paie, RH, GTA et DSN. Elle permet d'indexer des documents métier (CCN, doc produit, CDC client, guides…) et d'obtenir des réponses sourcées en langage naturel, ainsi que d'analyser automatiquement la couverture d'un cahier des charges client.

Éditée par **Opsidium**.

---

## Fonctionnalités

| Onglet | Description |
|---|---|
| **Indexation** | Upload de documents (PDF, DOCX, TXT, MD), jobs d'ingestion async, gestion du corpus utilisateur |
| **Chat** | Conversations avec RAG hybride (dense + sparse + reranker), citations, streaming SSE, feedback ±1 |
| **Analyse d'écarts** | Workspace clients/CDCs (routing par URL), lancement d'analyse async, rapport (donut, filtres, qualification slide-over, vue Tableau), export xlsx/md, **import de corrections humaines** (Excel enrichi 3 colonnes : verdict, description corrigée, notes) |
| **Référentiels** *(admin)* | Méthodologie interne Opsidium ; upload PDF/DOCX/XLSX (jusqu'à 50 MB) avec **indexation async sérialisée** (queue 1 job en parallèle, bandeau d'avancement, notification de fin) — collection `referentiels_opsidium` interrogée par le pipeline d'analyse CDC uniquement |
| **Évaluation RAGAS** | Évaluation de la qualité du RAG sur un CSV `question, ground_truth` (4 métriques) |
| **Notifications** | Cloche temps-réel (succès/erreur des jobs longs : ingestion CDC, analyse, indexation référentiels, import corrections) |
| **Paramètres** | Clé API OpenAI chiffrée, sélection des modèles LLM (admin), informations pipeline |
| **Utilisateurs** | Gestion des comptes (self-service mot de passe + admin CRUD utilisateurs) |

---

## Stack technique

### Pipeline RAG (`v4.7.0`)
- **Embeddings** : `BAAI/bge-m3` (multilingue, 1024 dim, mutex CPU pour éviter saturation)
- **Reranker** : `BAAI/bge-reranker-v2-m3`
- **Chunking** : sémantique + structure-aware (`v2`)
- **Parsers** : PDF (PyMuPDF), DOCX (`python-docx` — préserve paragraphes + tableaux), XLSX/XLS, TXT, MD
- **Retrieval hybride** : dense Qdrant + BM25 → RRF (k=60) → top-K rerank
- **Gap analysis** : extraction d'exigences map-reduce, dedup sémantique, HyDE, re-pass GPT-4o sur les ambigus, cache disque, **overrides corrections humaines** (matching par content_key + fallback sur titre)

### Architecture
- **Frontend** : Next.js 15 + TypeScript + Tailwind + Radix UI ; middleware en runtime `nodejs` (pour uploads >10 MB)
- **Backend** : FastAPI + LangChain (LCEL) + LangSmith-compatible ; workers async (`gap_analysis_jobs`, `ingestion_jobs`) + queue sérialisée pour indexation référentiels
- **Stockage vectoriel** : Qdrant (collection per-user `rag_<user_id>` + collection partagée `referentiels_opsidium` admin uniquement)
- **Stockage relationnel** : SQLite (users, conversations, workspace, jobs, corrections, notifications)
- **Auth** : JWT HS256 (cookie session) + rôles `admin` / `user`
- **LLM** : OpenAI GPT-4o-mini par défaut (clé fournie par l'utilisateur, chiffrée Fernet)

---

## Prérequis

- **Docker** ≥ 24 et **Docker Compose** ≥ 2.20
- **Clé API OpenAI** (saisie dans Paramètres, chiffrée et stockée par utilisateur)

---

## Installation

```bash
# 1. Cloner le projet
git clone https://github.com/oss-opsi/rag-mvp-local.git
cd rag-mvp-local

# 2. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env, en particulier JWT_SECRET :
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 3. Construire et démarrer
docker compose up --build -d
```

La première exécution télécharge les modèles d'embeddings et reranker (~1 Go) — prévoir quelques minutes.

---

## Mise à jour sur VPS

```bash
cd /opt/rag-mvp-local
git pull
docker compose up -d --build
```

---

## Accès aux services

| Service | URL |
|---|---|
| Frontend Tell me | http://localhost:8501 (mappé sur le port interne 3000) |
| API FastAPI (Swagger) | http://localhost:8000/docs |
| Tableau de bord Qdrant | http://localhost:6333/dashboard |

---

## Premier démarrage

1. **Inscription** : à la première connexion, créer le compte `daniel` (ou autre) — il sera automatiquement promu `admin`
2. **Saisir la clé OpenAI** dans **Paramètres** (chiffrée localement)
3. **Indexer des documents** dans **Indexation** (drag & drop)
4. **Poser des questions** dans **Chat** ou **lancer une analyse de CDC** dans **Analyse d'écarts**

---

## Variables d'environnement

| Variable | Valeur par défaut | Description |
|---|---|---|
| `JWT_SECRET` | *(insécurisé en dev)* | **⚠️ À changer en production** — secret de signature JWT |
| `QDRANT_URL` | `http://qdrant:6333` | URL du serveur Qdrant |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Modèle d'embeddings (1024 dim) |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | Modèle cross-encoder de rerank |
| `LLM_MODEL` | `gpt-4o-mini` | Modèle OpenAI par défaut |
| `LLM_TEMPERATURE` | `0.1` | Température du LLM |
| `DATA_DIR` | `/data` | Répertoire des données (SQLite, BM25) |
| `CHUNK_SIZE` | `800` | Taille des fragments (chars) |
| `CHUNK_OVERLAP` | `120` | Chevauchement des fragments |
| `RETRIEVAL_K` | `5` | Top-K final (chat) |
| `BACKEND_URL` | `http://backend:8000` | URL backend (depuis le frontend) |

**Important** : la clé API OpenAI **n'est jamais stockée dans les variables d'environnement**. Elle est saisie par l'utilisateur dans l'onglet Paramètres et chiffrée avec Fernet en SQLite.

---

## Structure du projet

```
rag-mvp-local/
├── README.md                       # Ce fichier
├── ROLLBACK.md                     # Procédure de retour au tag v3.9.0-stable
├── BACKLOG.md                      # (à venir) Roadmap v4
├── docker-compose.yml              # Orchestration Docker (qdrant + backend + frontend)
├── .env.example                    # Variables d'environnement (exemple)
├── data/                           # SQLite + Qdrant + BM25 (volume Docker)
├── backend/
│   ├── Dockerfile
│   ├── main.py                     # API FastAPI v3.1
│   ├── requirements.txt
│   └── rag/                        # Modules métier (chain, retriever, gap_analysis, etc.)
└── frontend-next/
    ├── Dockerfile
    ├── app/                        # Pages Next.js App Router
    ├── components/                 # Composants React (incl. shadcn/ui)
    ├── lib/                        # Client API typé, helpers
    ├── middleware.ts               # Auth cookie session
    └── package.json
```

---

## Arrêter / réinitialiser

```bash
# Arrêter les conteneurs
docker compose down

# Arrêter et effacer toutes les données (⚠️ irréversible)
docker compose down -v
```

---

## Rollback

En cas de problème, voir [ROLLBACK.md](./ROLLBACK.md) — tag stable de référence : **`v4.7.1-uploads-fix`**.

---

## Technologies

- [Next.js 15](https://nextjs.org/) — framework React
- [Tailwind CSS](https://tailwindcss.com/) + [Radix UI](https://www.radix-ui.com/) — UI
- [FastAPI](https://fastapi.tiangolo.com/) — API REST backend
- [LangChain](https://python.langchain.com/) — chaîne RAG (LCEL)
- [Qdrant](https://qdrant.tech/) — base vectorielle
- [Hugging Face / sentence-transformers](https://huggingface.co/) — embeddings & reranker
- [rank-bm25](https://github.com/dorianbrown/rank_bm25) — recherche BM25
- [RAGAS](https://docs.ragas.io/) — évaluation RAG
- [PyJWT](https://pyjwt.readthedocs.io/) + [bcrypt](https://pypi.org/project/bcrypt/) — auth
- [OpenAI GPT-4o-mini](https://openai.com/) — génération

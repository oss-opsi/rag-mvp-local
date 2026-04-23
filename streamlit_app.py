"""
streamlit_app.py — Version autonome (sans Docker, sans FastAPI).

Qdrant en mode local (stockage sur disque : ./qdrant_data).
Toute l'interface est en français.

Usage :
    pip install -r requirements.txt
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import hashlib
import logging
import os
import pickle
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="RAG MVP — Mode Autonome",
    page_icon="📄",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Lazy imports (heavy libraries loaded only when needed)
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Local Qdrant data directory
_QDRANT_DATA_DIR = "./qdrant_data"
_BM25_CORPUS_FILE = "./qdrant_data/bm25_corpus.pkl"
_COLLECTION_NAME = "rag_documents_standalone"
_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 120
_RRF_K = 60


# ---------------------------------------------------------------------------
# Singleton helpers (cached with st.cache_resource)
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner="Chargement du modèle d'embeddings…")
def _get_embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=_EMBEDDING_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )


@st.cache_resource(show_spinner="Connexion à Qdrant (mode local)…")
def _get_qdrant_client():
    from qdrant_client import QdrantClient

    Path(_QDRANT_DATA_DIR).mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=_QDRANT_DATA_DIR)


def _ensure_collection(client) -> None:
    from qdrant_client.http.models import Distance, VectorParams

    existing = [c.name for c in client.get_collections().collections]
    if _COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=_COLLECTION_NAME,
            vectors_config=VectorParams(size=_EMBEDDING_DIM, distance=Distance.COSINE),
        )


def _get_vector_store(client, embeddings):
    from langchain_qdrant import QdrantVectorStore

    return QdrantVectorStore(
        client=client,
        collection_name=_COLLECTION_NAME,
        embedding=embeddings,
    )


# ---------------------------------------------------------------------------
# BM25 corpus management (file-based persistence)
# ---------------------------------------------------------------------------


def _load_bm25_corpus() -> list[dict[str, Any]]:
    if "bm25_corpus" in st.session_state:
        return st.session_state.bm25_corpus
    Path(_QDRANT_DATA_DIR).mkdir(parents=True, exist_ok=True)
    if Path(_BM25_CORPUS_FILE).exists():
        with open(_BM25_CORPUS_FILE, "rb") as fh:
            corpus = pickle.load(fh)
        st.session_state.bm25_corpus = corpus
        return corpus
    st.session_state.bm25_corpus = []
    return []


def _save_bm25_corpus(corpus: list[dict[str, Any]]) -> None:
    Path(_QDRANT_DATA_DIR).mkdir(parents=True, exist_ok=True)
    with open(_BM25_CORPUS_FILE, "wb") as fh:
        pickle.dump(corpus, fh)
    st.session_state.bm25_corpus = corpus


def _reset_bm25_corpus() -> None:
    if Path(_BM25_CORPUS_FILE).exists():
        os.remove(_BM25_CORPUS_FILE)
    st.session_state.bm25_corpus = []


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def ingest_pdf_standalone(file_path: str, source_name: str) -> int:
    """Ingest a PDF into the local Qdrant and the BM25 corpus."""
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # Load
    loader = PyPDFLoader(file_path)
    pages = loader.load()

    # Split
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    docs = splitter.split_documents(pages)

    # Enrich metadata
    doc_hash = hashlib.md5(source_name.encode()).hexdigest()[:8]
    for i, doc in enumerate(docs):
        doc.metadata["source"] = source_name
        doc.metadata["chunk_id"] = f"{doc_hash}_{i}"
        if "page" in doc.metadata:
            doc.metadata["page"] = int(doc.metadata["page"]) + 1
        else:
            doc.metadata["page"] = 1

    # Qdrant
    embeddings = _get_embeddings()
    client = _get_qdrant_client()
    _ensure_collection(client)
    vector_store = _get_vector_store(client, embeddings)
    vector_store.add_documents(docs)

    # BM25
    corpus = _load_bm25_corpus()
    for doc in docs:
        corpus.append(
            {
                "id": doc.metadata["chunk_id"],
                "text": doc.page_content,
                "metadata": doc.metadata,
            }
        )
    _save_bm25_corpus(corpus)

    return len(docs)


# ---------------------------------------------------------------------------
# Hybrid retrieval (dense + BM25 + RRF)
# ---------------------------------------------------------------------------


def _dense_search(query: str, k: int) -> list[tuple[str, dict, float]]:
    embeddings = _get_embeddings()
    client = _get_qdrant_client()
    vector_store = _get_vector_store(client, embeddings)
    results = vector_store.similarity_search_with_score(query, k=k)
    return [(doc.page_content, doc.metadata, float(score)) for doc, score in results]


def _sparse_search(query: str, k: int) -> list[tuple[str, dict, float]]:
    from rank_bm25 import BM25Okapi

    corpus = _load_bm25_corpus()
    if not corpus:
        return []
    tokenized_corpus = [entry["text"].lower().split() for entry in corpus]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query.lower().split())
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:k]
    return [
        (corpus[i]["text"], corpus[i]["metadata"], float(s))
        for i, s in indexed
        if s > 0
    ]


def _rrf_fuse(
    dense: list[tuple[str, dict, float]],
    sparse: list[tuple[str, dict, float]],
    k: int,
) -> list[dict[str, Any]]:
    rrf_scores: dict[str, float] = {}
    doc_store: dict[str, dict] = {}

    def key(text: str, meta: dict) -> str:
        return meta.get("chunk_id", text[:80])

    def rrf(rank: int) -> float:
        return 1.0 / (_RRF_K + rank + 1)

    for rank, (text, meta, _) in enumerate(dense):
        k_ = key(text, meta)
        rrf_scores[k_] = rrf_scores.get(k_, 0.0) + rrf(rank)
        doc_store[k_] = {"text": text, "metadata": meta}

    for rank, (text, meta, _) in enumerate(sparse):
        k_ = key(text, meta)
        rrf_scores[k_] = rrf_scores.get(k_, 0.0) + rrf(rank)
        if k_ not in doc_store:
            doc_store[k_] = {"text": text, "metadata": meta}

    sorted_keys = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)[:k]
    return [
        {
            "text": doc_store[k_]["text"],
            "metadata": doc_store[k_]["metadata"],
            "rrf_score": round(rrf_scores[k_], 6),
        }
        for k_ in sorted_keys
    ]


def hybrid_retrieve(query: str, k: int = 5) -> list[dict[str, Any]]:
    dense = _dense_search(query, k_dense := 20)
    sparse = _sparse_search(query, k_sparse := 20)
    return _rrf_fuse(dense, sparse, k)


# ---------------------------------------------------------------------------
# RAG chain
# ---------------------------------------------------------------------------


def answer_question_standalone(
    question: str, openai_api_key: str, k: int = 5
) -> dict[str, Any]:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnablePassthrough
    from langchain_openai import ChatOpenAI

    chunks = hybrid_retrieve(question, k=k)
    if not chunks:
        return {
            "answer": "Je ne sais pas. Aucun document pertinent n'a été trouvé dans l'index.",
            "sources": [],
        }

    # Format context
    context_parts = []
    for chunk in chunks:
        meta = chunk["metadata"]
        src = meta.get("source", "inconnu")
        page = meta.get("page", "?")
        context_parts.append(f"[{src} p.{page}]\n{chunk['text']}")
    context = "\n\n---\n\n".join(context_parts)

    # Prompt
    system_prompt = (
        "Tu es un assistant expert en analyse de documents.\n"
        "Tu réponds UNIQUEMENT à partir du contexte fourni ci-dessous.\n"
        "Si la réponse ne figure pas dans le contexte, réponds exactement : \"Je ne sais pas.\"\n"
        "Cite toujours tes sources entre crochets, par exemple [rapport.pdf p.3].\n"
        "Sois précis, concis et professionnel.\n\n"
        "Contexte :\n{context}"
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{question}")]
    )

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.1,
        api_key=openai_api_key,
    )

    chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    answer = chain.invoke({"context": context, "question": question})

    sources = [
        {
            "text": c["text"],
            "source": c["metadata"].get("source", "inconnu"),
            "page": c["metadata"].get("page", "?"),
            "score": c["rrf_score"],
        }
        for c in chunks
    ]
    return {"answer": answer, "sources": sources}


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "chat_history" not in st.session_state:
    st.session_state.chat_history: list[dict] = []

if "indexed_docs" not in st.session_state:
    st.session_state.indexed_docs: list[str] = []

# Pre-load BM25 corpus
_load_bm25_corpus()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚙️ Configuration")

    openai_key = st.text_input(
        "Clé API OpenAI",
        type="password",
        placeholder="sk-...",
        help="Votre clé OpenAI. Elle n'est jamais stockée sur disque.",
    )

    st.info("Mode autonome — Qdrant stocké localement dans `./qdrant_data/`")

    st.divider()

    # Stats
    try:
        client = _get_qdrant_client()
        _ensure_collection(client)
        info = client.get_collection(_COLLECTION_NAME)
        vec_count = info.points_count or 0
        st.metric("Vecteurs indexés", vec_count)
    except Exception:
        st.metric("Vecteurs indexés", "—")

    corpus_size = len(_load_bm25_corpus())
    st.metric("Fragments BM25", corpus_size)

    st.divider()

    # Reset
    if st.button("🗑️ Réinitialiser l'index", type="secondary"):
        try:
            client = _get_qdrant_client()
            existing = [c.name for c in client.get_collections().collections]
            if _COLLECTION_NAME in existing:
                client.delete_collection(_COLLECTION_NAME)
            _ensure_collection(client)
            _reset_bm25_corpus()
            st.session_state.indexed_docs = []
            st.session_state.chat_history = []
            # Invalidate cached resources
            st.cache_resource.clear()
            st.success("Index réinitialisé.")
            st.rerun()
        except Exception as exc:
            st.error(f"Erreur : {exc}")

    if st.session_state.indexed_docs:
        st.divider()
        st.markdown("**Documents indexés :**")
        for doc in st.session_state.indexed_docs:
            st.markdown(f"- 📄 {doc}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

st.title("📚 RAG MVP — Mode Autonome (sans Docker)")
st.caption(
    "Recherche dense (Qdrant local) + BM25 + fusion RRF · LLM : GPT-4o-mini · "
    "Embeddings : BAAI/bge-small-en-v1.5"
)

# ---------------------------------------------------------------------------
# Upload section
# ---------------------------------------------------------------------------

st.subheader("1. Indexer vos documents")

uploaded_files = st.file_uploader(
    "Glissez-déposez vos fichiers PDF ici",
    type=["pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if uploaded_files and st.button("📥 Indexer les documents", type="primary"):
    progress = st.progress(0, text="Démarrage de l'indexation…")
    total = len(uploaded_files)
    for i, f in enumerate(uploaded_files):
        progress.progress(i / total, text=f"Indexation de {f.name} ({i+1}/{total})…")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name
        try:
            chunk_count = ingest_pdf_standalone(tmp_path, f.name)
            if f.name not in st.session_state.indexed_docs:
                st.session_state.indexed_docs.append(f.name)
            st.success(f"✅ **{f.name}** — {chunk_count} fragments indexés")
        except Exception as exc:
            st.error(f"❌ Erreur lors de l'indexation de {f.name} : {exc}")
        finally:
            os.unlink(tmp_path)
    progress.progress(1.0, text="Indexation terminée.")

st.divider()

# ---------------------------------------------------------------------------
# Chat section
# ---------------------------------------------------------------------------

st.subheader("2. Poser une question")

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("sources"):
            with st.expander("📚 Sources"):
                for src in msg["sources"]:
                    st.markdown(
                        f"**{src.get('source', '?')} — page {src.get('page', '?')}** "
                        f"_(score RRF : {src.get('score', 0):.4f})_"
                    )
                    st.caption(src.get("text", ""))
                    st.divider()

if question := st.chat_input("Posez votre question sur les documents indexés…"):
    if not openai_key:
        st.warning("⚠️ Veuillez renseigner votre clé API OpenAI dans la barre latérale.")
        st.stop()

    st.session_state.chat_history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Recherche en cours…"):
            try:
                result = answer_question_standalone(question, openai_key)
                answer = result["answer"]
                sources = result["sources"]

                st.markdown(answer)
                if sources:
                    with st.expander("📚 Sources"):
                        for src in sources:
                            st.markdown(
                                f"**{src.get('source', '?')} — page {src.get('page', '?')}** "
                                f"_(score RRF : {src.get('score', 0):.4f})_"
                            )
                            st.caption(src.get("text", ""))
                            st.divider()

                st.session_state.chat_history.append(
                    {"role": "assistant", "content": answer, "sources": sources}
                )
            except Exception as exc:
                st.error(f"❌ Erreur : {exc}")

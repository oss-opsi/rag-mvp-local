"""
streamlit_app.py — Version autonome (sans Docker, sans FastAPI).

Qdrant en mode mémoire (pas de persistance sur disque).
L'index est réinitialisé à chaque redémarrage de l'application.
Toute l'interface est en français.

Usage :
    pip install -r requirements.txt
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import hashlib
import logging
import os
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

_COLLECTION_NAME = "rag_documents_standalone"
_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 120
_RRF_K = 60

# Supported file extensions
_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


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


@st.cache_resource(show_spinner="Initialisation de Qdrant en mémoire…")
def _get_qdrant_client():
    from qdrant_client import QdrantClient

    # In-memory mode: no data persisted to disk
    return QdrantClient(":memory:")


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
# BM25 corpus management (in-memory only — no pickle file)
# ---------------------------------------------------------------------------


def _load_bm25_corpus() -> list[dict[str, Any]]:
    """Return the BM25 corpus stored in session state (in-memory only)."""
    if "bm25_corpus" not in st.session_state:
        st.session_state.bm25_corpus = []
    return st.session_state.bm25_corpus


def _save_bm25_corpus(corpus: list[dict[str, Any]]) -> None:
    """Persist BM25 corpus to session state (in-memory only)."""
    st.session_state.bm25_corpus = corpus


def _reset_bm25_corpus() -> None:
    """Clear the BM25 corpus in session state."""
    st.session_state.bm25_corpus = []


# ---------------------------------------------------------------------------
# Cross-encoder reranker (lazy-loaded singleton)
# ---------------------------------------------------------------------------

_cross_encoder_instance = None


def _get_cross_encoder():
    """Lazy-load and return the CrossEncoder singleton."""
    global _cross_encoder_instance
    if _cross_encoder_instance is None:
        from sentence_transformers import CrossEncoder
        _cross_encoder_instance = CrossEncoder("BAAI/bge-reranker-base")
    return _cross_encoder_instance


def _cross_encoder_rerank(
    query: str,
    chunks: list[dict[str, Any]],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Score chunks with the cross-encoder and return top_n."""
    if not chunks:
        return []
    ce = _get_cross_encoder()
    pairs = [(query, c["text"]) for c in chunks]
    scores = ce.predict(pairs)
    scored = []
    for chunk, score in zip(chunks, scores):
        enriched = dict(chunk)
        enriched["metadata"] = dict(chunk["metadata"])
        enriched["metadata"]["rerank_score"] = float(score)
        scored.append((float(score), enriched))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored[:top_n]]


# ---------------------------------------------------------------------------
# Document loading by extension
# ---------------------------------------------------------------------------


def _load_documents(file_path: str, ext: str):
    """Load a document using the appropriate loader for the file extension."""
    ext = ext.lower()
    if ext == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader
        loader = PyPDFLoader(file_path)
    elif ext == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader
        loader = Docx2txtLoader(file_path)
    elif ext in {".txt", ".md"}:
        from langchain_community.document_loaders import TextLoader
        loader = TextLoader(file_path, encoding="utf-8")
    else:
        raise ValueError(
            f"Format non supporté : '{ext}'. "
            f"Formats acceptés : PDF, DOCX, TXT, MD"
        )
    return loader.load()


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def ingest_document_standalone(file_path: str, source_name: str, ext: str) -> int:
    """Ingest a document into the in-memory Qdrant and the BM25 corpus."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # Load
    pages = _load_documents(file_path, ext)

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

    # Qdrant (in-memory)
    embeddings = _get_embeddings()
    client = _get_qdrant_client()
    _ensure_collection(client)
    vector_store = _get_vector_store(client, embeddings)
    vector_store.add_documents(docs)

    # BM25 (in-memory via session state)
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


def hybrid_retrieve(
    query: str,
    k: int = 5,
    use_reranker: bool = False,
) -> list[dict[str, Any]]:
    """Hybrid search with optional cross-encoder reranking."""
    # Retrieve more candidates when reranking
    rrf_k = 15 if use_reranker else k
    dense = _dense_search(query, k_dense := 20)
    sparse = _sparse_search(query, k_sparse := 20)
    fused = _rrf_fuse(dense, sparse, rrf_k)

    if use_reranker and fused:
        fused = _cross_encoder_rerank(query, fused, top_n=k)

    return fused


# ---------------------------------------------------------------------------
# RAG chain — non-streaming
# ---------------------------------------------------------------------------


def _build_context(chunks: list[dict[str, Any]]) -> str:
    parts = []
    for chunk in chunks:
        meta = chunk["metadata"]
        src = meta.get("source", "inconnu")
        page = meta.get("page", "?")
        parts.append(f"[{src} p.{page}]\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


def _build_llm_chain(openai_api_key: str):
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnablePassthrough
    from langchain_openai import ChatOpenAI

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
        streaming=True,
    )
    chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain


def stream_answer_standalone(
    question: str,
    openai_api_key: str,
    k: int = 5,
    use_reranker: bool = False,
):
    """
    Returns (token_generator, sources) for streaming display.
    Retrieval is done synchronously first; only LLM generation is streamed.
    """
    chunks = hybrid_retrieve(question, k=k, use_reranker=use_reranker)

    if not chunks:
        def _empty():
            yield "Je ne sais pas. Aucun document pertinent n'a été trouvé dans l'index."
        return _empty(), []

    sources = [
        {
            "text": c["text"],
            "source": c["metadata"].get("source", "inconnu"),
            "page": c["metadata"].get("page", "?"),
            "score": c["rrf_score"],
            "rerank_score": c["metadata"].get("rerank_score"),
        }
        for c in chunks
    ]

    context = _build_context(chunks)
    chain = _build_llm_chain(openai_api_key)

    def _token_gen():
        for token in chain.stream({"context": context, "question": question}):
            yield token

    return _token_gen(), sources


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "chat_history" not in st.session_state:
    st.session_state.chat_history: list[dict] = []

if "indexed_docs" not in st.session_state:
    st.session_state.indexed_docs: list[str] = []

# Initialise BM25 corpus (in-memory)
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

    st.info("Qdrant en mémoire — l'index est réinitialisé à chaque redémarrage")

    st.divider()

    # Cross-encoder reranker toggle
    use_reranker = st.checkbox(
        "Activer le cross-encoder reranker (plus précis, + lent)",
        value=False,
        help="Utilise BAAI/bge-reranker-base pour reranker les résultats après RRF.",
    )

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

    # Reset — recreates the in-memory collection
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
    "Recherche dense (Qdrant mémoire) + BM25 + fusion RRF · LLM : GPT-4o-mini · "
    "Embeddings : BAAI/bge-small-en-v1.5"
)

# ---------------------------------------------------------------------------
# Upload section
# ---------------------------------------------------------------------------

st.subheader("1. Indexer vos documents")

uploaded_files = st.file_uploader(
    "Glissez-déposez vos fichiers ici (PDF, DOCX, TXT, MD — max 200 Mo)",
    type=["pdf", "docx", "txt", "md"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if uploaded_files and st.button("📥 Indexer les documents", type="primary"):
    progress = st.progress(0, text="Démarrage de l'indexation…")
    total = len(uploaded_files)
    for i, f in enumerate(uploaded_files):
        progress.progress(i / total, text=f"Indexation de {f.name} ({i+1}/{total})…")
        ext = Path(f.name).suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            st.error(f"❌ Format non supporté : {f.name}")
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name
        try:
            chunk_count = ingest_document_standalone(tmp_path, f.name, ext)
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
                    rrf_score = src.get("score", 0)
                    rerank_score = src.get("rerank_score")
                    score_text = f"_(score RRF : {rrf_score:.4f}"
                    if rerank_score is not None:
                        score_text += f" · rerank : {rerank_score:.4f}"
                    score_text += ")_"
                    st.markdown(
                        f"**{src.get('source', '?')} — page {src.get('page', '?')}** {score_text}"
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
        try:
            token_gen, sources = stream_answer_standalone(
                question, openai_key, k=5, use_reranker=use_reranker
            )
            # Stream tokens token-by-token
            answer = st.write_stream(token_gen)

            # Show sources after streaming completes
            if sources:
                with st.expander("📚 Sources"):
                    for src in sources:
                        rrf_score = src.get("score", 0)
                        rerank_score = src.get("rerank_score")
                        score_text = f"_(score RRF : {rrf_score:.4f}"
                        if rerank_score is not None:
                            score_text += f" · rerank : {rerank_score:.4f}"
                        score_text += ")_"
                        st.markdown(
                            f"**{src.get('source', '?')} — page {src.get('page', '?')}** {score_text}"
                        )
                        st.caption(src.get("text", ""))
                        st.divider()

            st.session_state.chat_history.append(
                {"role": "assistant", "content": answer or "", "sources": sources}
            )
        except Exception as exc:
            st.error(f"❌ Erreur : {exc}")

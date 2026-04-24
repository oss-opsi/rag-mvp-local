"""
streamlit_app.py — Version autonome v3 (sans Docker, sans FastAPI).

Nouveautés v3 Phase A :
  1. Évaluation RAGAS (onglet dédié)
  2. Historique des conversations (SQLite + export JSON)
  3. Authentification multi-utilisateurs (streamlit-authenticator + mode invité)

Qdrant en mode mémoire (pas de persistance sur disque).
L'index Qdrant est réinitialisé à chaque redémarrage de l'application.
Toute l'interface est en français.

Usage :
    pip install -r requirements.txt
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="RAG MVP v3 — Mode Autonome",
    page_icon="📄",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Ensure data/ directory exists (for SQLite databases)
# ---------------------------------------------------------------------------

Path("./data").mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Lazy imports & logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 120
_RRF_K = 60
_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# ---------------------------------------------------------------------------
# Auth configuration
# ---------------------------------------------------------------------------

_AUTH_COOKIE_NAME = "rag_mvp_auth"
_AUTH_COOKIE_KEY = os.getenv("AUTH_COOKIE_KEY", "rag-mvp-v3-secret-dev-key-change-in-prod")
_AUTH_COOKIE_EXPIRY_DAYS = 7

# ---------------------------------------------------------------------------
# Singleton helpers
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

    return QdrantClient(":memory:")


@st.cache_resource
def _get_conversation_db():
    """Singleton ConversationDB instance."""
    from backend.rag.history import ConversationDB

    return ConversationDB()


def _collection_name(user_id: str) -> str:
    """Return per-user Qdrant collection name."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)
    return f"rag_{safe}"


def _ensure_collection(client, user_id: str) -> None:
    from qdrant_client.http.models import Distance, VectorParams

    col_name = _collection_name(user_id)
    existing = [c.name for c in client.get_collections().collections]
    if col_name not in existing:
        client.create_collection(
            collection_name=col_name,
            vectors_config=VectorParams(size=_EMBEDDING_DIM, distance=Distance.COSINE),
        )


def _get_vector_store(client, embeddings, user_id: str):
    from langchain_qdrant import QdrantVectorStore

    return QdrantVectorStore(
        client=client,
        collection_name=_collection_name(user_id),
        embedding=embeddings,
    )


# ---------------------------------------------------------------------------
# BM25 corpus management (per-user, in-memory via session state)
# ---------------------------------------------------------------------------


def _bm25_key(user_id: str) -> str:
    return f"bm25_corpus_{user_id}"


def _load_bm25_corpus(user_id: str) -> list[dict[str, Any]]:
    key = _bm25_key(user_id)
    if key not in st.session_state:
        st.session_state[key] = []
    return st.session_state[key]


def _save_bm25_corpus(user_id: str, corpus: list[dict[str, Any]]) -> None:
    st.session_state[_bm25_key(user_id)] = corpus


def _reset_bm25_corpus(user_id: str) -> None:
    st.session_state[_bm25_key(user_id)] = []


# ---------------------------------------------------------------------------
# Cross-encoder reranker
# ---------------------------------------------------------------------------

_cross_encoder_instance = None


def _get_cross_encoder():
    global _cross_encoder_instance
    if _cross_encoder_instance is None:
        from sentence_transformers import CrossEncoder

        _cross_encoder_instance = CrossEncoder("BAAI/bge-reranker-base")
    return _cross_encoder_instance


def _cross_encoder_rerank(query: str, chunks: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
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
# Document loading
# ---------------------------------------------------------------------------


def _load_documents(file_path: str, ext: str):
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
        raise ValueError(f"Format non supporté : '{ext}'. Formats acceptés : PDF, DOCX, TXT, MD")
    return loader.load()


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def ingest_document_standalone(file_path: str, source_name: str, ext: str, user_id: str) -> int:
    """Ingest a document into per-user Qdrant collection and BM25 corpus."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    pages = _load_documents(file_path, ext)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    docs = splitter.split_documents(pages)

    doc_hash = hashlib.md5(source_name.encode()).hexdigest()[:8]
    for i, doc in enumerate(docs):
        doc.metadata["source"] = source_name
        doc.metadata["chunk_id"] = f"{doc_hash}_{i}"
        if "page" in doc.metadata:
            doc.metadata["page"] = int(doc.metadata["page"]) + 1
        else:
            doc.metadata["page"] = 1

    embeddings = _get_embeddings()
    client = _get_qdrant_client()
    _ensure_collection(client, user_id)
    vector_store = _get_vector_store(client, embeddings, user_id)
    vector_store.add_documents(docs)

    corpus = _load_bm25_corpus(user_id)
    for doc in docs:
        corpus.append({"id": doc.metadata["chunk_id"], "text": doc.page_content, "metadata": doc.metadata})
    _save_bm25_corpus(user_id, corpus)

    return len(docs)


# ---------------------------------------------------------------------------
# Hybrid retrieval (dense + BM25 + RRF)
# ---------------------------------------------------------------------------


def _dense_search(query: str, k: int, user_id: str) -> list[tuple[str, dict, float]]:
    embeddings = _get_embeddings()
    client = _get_qdrant_client()
    vector_store = _get_vector_store(client, embeddings, user_id)
    results = vector_store.similarity_search_with_score(query, k=k)
    return [(doc.page_content, doc.metadata, float(score)) for doc, score in results]


def _sparse_search(query: str, k: int, user_id: str) -> list[tuple[str, dict, float]]:
    from rank_bm25 import BM25Okapi

    corpus = _load_bm25_corpus(user_id)
    if not corpus:
        return []
    tokenized_corpus = [entry["text"].lower().split() for entry in corpus]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query.lower().split())
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:k]
    return [(corpus[i]["text"], corpus[i]["metadata"], float(s)) for i, s in indexed if s > 0]


def _rrf_fuse(
    dense: list[tuple[str, dict, float]],
    sparse: list[tuple[str, dict, float]],
    k: int,
) -> list[dict[str, Any]]:
    rrf_scores: dict[str, float] = {}
    doc_store: dict[str, dict] = {}

    def _key(text: str, meta: dict) -> str:
        return meta.get("chunk_id", text[:80])

    def _rrf(rank: int) -> float:
        return 1.0 / (_RRF_K + rank + 1)

    for rank, (text, meta, _) in enumerate(dense):
        k_ = _key(text, meta)
        rrf_scores[k_] = rrf_scores.get(k_, 0.0) + _rrf(rank)
        doc_store[k_] = {"text": text, "metadata": meta}

    for rank, (text, meta, _) in enumerate(sparse):
        k_ = _key(text, meta)
        rrf_scores[k_] = rrf_scores.get(k_, 0.0) + _rrf(rank)
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


def hybrid_retrieve(query: str, k: int = 5, use_reranker: bool = False, user_id: str = "guest") -> list[dict[str, Any]]:
    """Hybrid search with optional cross-encoder reranking."""
    rrf_k = 15 if use_reranker else k
    dense = _dense_search(query, 20, user_id)
    sparse = _sparse_search(query, 20, user_id)
    fused = _rrf_fuse(dense, sparse, rrf_k)
    if use_reranker and fused:
        fused = _cross_encoder_rerank(query, fused, top_n=k)
    return fused


# ---------------------------------------------------------------------------
# RAG chain
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
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{question}")])
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, api_key=openai_api_key, streaming=True)
    chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain


def get_answer_non_streaming(question: str, context: str, openai_api_key: str) -> str:
    """Non-streaming answer for RAGAS evaluation."""
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnablePassthrough
    from langchain_openai import ChatOpenAI

    system_prompt = (
        "Tu es un assistant expert en analyse de documents.\n"
        "Tu réponds UNIQUEMENT à partir du contexte fourni ci-dessous.\n"
        "Si la réponse ne figure pas dans le contexte, réponds exactement : \"Je ne sais pas.\"\n"
        "Sois précis et concis.\n\n"
        "Contexte :\n{context}"
    )
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{question}")])
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, api_key=openai_api_key, streaming=False)
    chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain.invoke({"context": context, "question": question})


def stream_answer_standalone(question: str, openai_api_key: str, k: int = 5, use_reranker: bool = False, user_id: str = "guest"):
    """
    Returns (token_generator, sources) for streaming display.
    Retrieval is done synchronously first; only LLM generation is streamed.
    """
    chunks = hybrid_retrieve(question, k=k, use_reranker=use_reranker, user_id=user_id)

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
# Auth helpers
# ---------------------------------------------------------------------------


def _build_authenticator():
    """Build a streamlit_authenticator.Authenticate instance from the DB."""
    try:
        import streamlit_authenticator as stauth
        from backend.rag.auth import list_users_for_authenticator

        credentials = list_users_for_authenticator()
        authenticator = stauth.Authenticate(
            credentials=credentials,
            cookie_name=_AUTH_COOKIE_NAME,
            cookie_key=_AUTH_COOKIE_KEY,
            cookie_expiry_days=_AUTH_COOKIE_EXPIRY_DAYS,
        )
        return authenticator
    except Exception as exc:
        logger.warning("Could not build authenticator: %s", exc)
        return None


def _score_color(score: float) -> str:
    """Return a CSS color string based on score threshold."""
    if math.isnan(score):
        return "#888888"
    if score >= 0.8:
        return "#28a745"
    if score >= 0.5:
        return "#fd7e14"
    return "#dc3545"


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = None
if "user_name" not in st.session_state:
    st.session_state.user_name = None
if "guest_mode" not in st.session_state:
    st.session_state.guest_mode = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history: list[dict] = []
if "indexed_docs" not in st.session_state:
    st.session_state.indexed_docs: list[str] = []
if "current_conversation_id" not in st.session_state:
    st.session_state.current_conversation_id = None
if "current_conversation_title" not in st.session_state:
    st.session_state.current_conversation_title = "Nouvelle conversation"
if "history_selected_conv" not in st.session_state:
    st.session_state.history_selected_conv = None


def _current_user_id() -> str:
    return st.session_state.username or "guest"


def _current_user_name() -> str:
    return st.session_state.user_name or "Invité"


# ---------------------------------------------------------------------------
# Authentication gate
# ---------------------------------------------------------------------------

def _show_auth_gate():
    """Display login / register / guest mode UI. Returns True when authenticated."""
    st.title("📚 RAG MVP v3 — Mode Autonome")
    st.caption("Recherche dense + BM25 + fusion RRF · RAGAS eval · Historique des conversations")

    login_tab, register_tab = st.tabs(["🔐 Connexion", "✍️ Inscription"])

    with login_tab:
        st.subheader("Se connecter")
        auth = _build_authenticator()
        if auth is not None:
            try:
                result = auth.login(location="main")
                # streamlit-authenticator sets session_state keys
                if st.session_state.get("authentication_status") is True:
                    st.session_state.authenticated = True
                    st.session_state.username = st.session_state.get("username")
                    st.session_state.user_name = st.session_state.get("name", st.session_state.username)
                    st.session_state.guest_mode = False
                    st.rerun()
                elif st.session_state.get("authentication_status") is False:
                    st.error("Nom d'utilisateur ou mot de passe incorrect.")
                else:
                    st.info("Entrez vos identifiants pour vous connecter.")
            except Exception as exc:
                st.warning(f"Erreur d'authentification : {exc}")
        else:
            st.warning("Module d'authentification non disponible. Utilisez le mode invité.")

        st.divider()
        st.markdown("**Pas de compte ?**")
        if st.button("🚀 Mode invité", help="Accès sans compte — index partagé avec les autres invités"):
            st.session_state.authenticated = True
            st.session_state.username = "guest"
            st.session_state.user_name = "Invité"
            st.session_state.guest_mode = True
            st.rerun()
        st.caption("Mode invité — votre index est partagé avec les autres invités et peut être réinitialisé à tout moment.")

    with register_tab:
        st.subheader("Créer un compte")
        with st.form("register_form"):
            reg_username = st.text_input("Nom d'utilisateur", placeholder="alice")
            reg_email = st.text_input("Email", placeholder="alice@example.com")
            reg_name = st.text_input("Nom complet", placeholder="Alice Dupont")
            reg_password = st.text_input("Mot de passe", type="password")
            reg_password2 = st.text_input("Confirmer le mot de passe", type="password")
            submitted = st.form_submit_button("S'inscrire", type="primary")

        if submitted:
            if reg_password != reg_password2:
                st.error("Les mots de passe ne correspondent pas.")
            else:
                try:
                    from backend.rag.auth import register_user

                    register_user(reg_username, reg_email, reg_name, reg_password)
                    st.success(f"✅ Compte créé pour **{reg_username}** ! Connectez-vous dans l'onglet Connexion.")
                except Exception as exc:
                    st.error(f"Erreur : {exc}")


# ===========================================================================
# MAIN APP — show auth gate if not authenticated
# ===========================================================================

if not st.session_state.authenticated:
    _show_auth_gate()
    st.stop()

# ---------------------------------------------------------------------------
# Authenticated: current user
# ---------------------------------------------------------------------------

user_id = _current_user_id()
user_name = _current_user_name()

# Initialise BM25 corpus for this user
_load_bm25_corpus(user_id)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚙️ Configuration")

    # User info
    if st.session_state.guest_mode:
        st.caption("Mode invité — index partagé")
    else:
        st.caption(f"Connecté en tant que : **{user_name}**")

    if not st.session_state.guest_mode:
        try:
            import streamlit_authenticator as stauth
            auth_sidebar = _build_authenticator()
            if auth_sidebar:
                auth_sidebar.logout(location="sidebar")
                if not st.session_state.get("authentication_status"):
                    st.session_state.authenticated = False
                    st.session_state.username = None
                    st.rerun()
        except Exception:
            if st.button("Se déconnecter"):
                st.session_state.authenticated = False
                st.session_state.username = None
                st.session_state.user_name = None
                st.rerun()
    else:
        if st.button("Se déconnecter / Changer de compte"):
            st.session_state.authenticated = False
            st.session_state.username = None
            st.session_state.user_name = None
            st.session_state.guest_mode = False
            st.rerun()

    st.divider()

    openai_key = st.text_input(
        "Clé API OpenAI",
        type="password",
        placeholder="sk-...",
        help="Votre clé OpenAI. Elle n'est jamais stockée sur disque.",
    )

    st.info("Qdrant en mémoire — l'index est réinitialisé à chaque redémarrage")

    st.divider()

    use_reranker = st.checkbox(
        "Activer le cross-encoder reranker (plus précis, + lent)",
        value=False,
        help="Utilise BAAI/bge-reranker-base pour reranker les résultats après RRF.",
    )

    st.divider()

    # Conversation actuelle
    conv_title = st.session_state.current_conversation_title
    st.markdown(f"**Conversation actuelle :** {conv_title}")

    st.divider()

    # Stats for current user
    try:
        client = _get_qdrant_client()
        _ensure_collection(client, user_id)
        info = client.get_collection(_collection_name(user_id))
        vec_count = info.points_count or 0
        st.metric("Vecteurs indexés", vec_count)
    except Exception:
        st.metric("Vecteurs indexés", "—")

    corpus_size = len(_load_bm25_corpus(user_id))
    st.metric("Fragments BM25", corpus_size)

    st.divider()

    if st.button("🗑️ Réinitialiser l'index", type="secondary"):
        try:
            client = _get_qdrant_client()
            col_name = _collection_name(user_id)
            existing = [c.name for c in client.get_collections().collections]
            if col_name in existing:
                client.delete_collection(col_name)
            _ensure_collection(client, user_id)
            _reset_bm25_corpus(user_id)
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
# Main title
# ---------------------------------------------------------------------------

st.title("📚 RAG MVP v3 — Mode Autonome")
st.caption(
    "Recherche dense (Qdrant mémoire) + BM25 + fusion RRF · LLM : GPT-4o-mini · "
    "Embeddings : BAAI/bge-small-en-v1.5"
)

# ---------------------------------------------------------------------------
# Upload section (always visible above tabs)
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
        progress.progress(i / total, text=f"Indexation de {f.name} ({i + 1}/{total})…")
        ext = Path(f.name).suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            st.error(f"❌ Format non supporté : {f.name}")
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name
        try:
            chunk_count = ingest_document_standalone(tmp_path, f.name, ext, user_id)
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
# Tabs
# ---------------------------------------------------------------------------

tab_chat, tab_eval, tab_history = st.tabs(["💬 Chat", "📊 Évaluation RAGAS", "🗂️ Historique"])

# ===========================================================================
# TAB 1 — Chat
# ===========================================================================

with tab_chat:
    st.subheader("2. Poser une question")

    # Display chat history
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
                        st.markdown(f"**{src.get('source', '?')} — page {src.get('page', '?')}** {score_text}")
                        st.caption(src.get("text", ""))
                        st.divider()

    if question := st.chat_input("Posez votre question sur les documents indexés…"):
        if not openai_key:
            st.warning("⚠️ Veuillez renseigner votre clé API OpenAI dans la barre latérale.")
            st.stop()

        # Ensure a conversation exists in DB
        db = _get_conversation_db()
        if not st.session_state.current_conversation_id:
            title = db.title_from_message(question)
            conv_id = db.create_conversation(user_id, title)
            st.session_state.current_conversation_id = conv_id
            st.session_state.current_conversation_title = title

        conv_id = st.session_state.current_conversation_id

        # Persist user message
        try:
            db.add_message(conv_id, "user", question)
        except Exception as exc:
            logger.warning("Could not persist user message: %s", exc)

        st.session_state.chat_history.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            try:
                token_gen, sources = stream_answer_standalone(
                    question, openai_key, k=5, use_reranker=use_reranker, user_id=user_id
                )
                answer = st.write_stream(token_gen)

                if sources:
                    with st.expander("📚 Sources"):
                        for src in sources:
                            rrf_score = src.get("score", 0)
                            rerank_score = src.get("rerank_score")
                            score_text = f"_(score RRF : {rrf_score:.4f}"
                            if rerank_score is not None:
                                score_text += f" · rerank : {rerank_score:.4f}"
                            score_text += ")_"
                            st.markdown(f"**{src.get('source', '?')} — page {src.get('page', '?')}** {score_text}")
                            st.caption(src.get("text", ""))
                            st.divider()

                st.session_state.chat_history.append(
                    {"role": "assistant", "content": answer or "", "sources": sources}
                )

                # Persist assistant message
                try:
                    db.add_message(conv_id, "assistant", answer or "", sources)
                except Exception as exc:
                    logger.warning("Could not persist assistant message: %s", exc)

            except Exception as exc:
                st.error(f"❌ Erreur : {exc}")


# ===========================================================================
# TAB 2 — RAGAS Evaluation
# ===========================================================================

with tab_eval:
    st.subheader("📊 Évaluation RAGAS")
    st.markdown(
        "Uploadez un CSV avec 2 colonnes : **`question`**, **`ground_truth`** (réponse de référence attendue). "
        "L'évaluation mesure 4 métriques RAGAS : fidélité, pertinence de la réponse, précision et rappel du contexte."
    )

    # Template download
    _template_csv = "question,ground_truth\n\"Qu'est-ce que RAG ?\",\"RAG signifie Retrieval-Augmented Generation.\"\n\"Quel modèle d'embeddings est utilisé ?\",\"BAAI/bge-small-en-v1.5\"\n"
    st.download_button(
        label="📥 Télécharger le modèle CSV",
        data=_template_csv,
        file_name="ragas_template.csv",
        mime="text/csv",
    )

    eval_file = st.file_uploader(
        "Uploader votre fichier CSV d'évaluation",
        type=["csv"],
        key="ragas_csv_upload",
    )

    has_index = len(_load_bm25_corpus(user_id)) > 0
    eval_disabled = not has_index or not openai_key

    if eval_disabled:
        if not has_index:
            st.warning("⚠️ Aucun document indexé. Indexez d'abord vos documents dans la section ci-dessus.")
        if not openai_key:
            st.warning("⚠️ Clé API OpenAI manquante (barre latérale).")

    if eval_file and st.button("🚀 Lancer l'évaluation", type="primary", disabled=eval_disabled):
        import pandas as pd

        try:
            df_input = pd.read_csv(eval_file)
        except Exception as exc:
            st.error(f"Impossible de lire le CSV : {exc}")
            st.stop()

        if "question" not in df_input.columns or "ground_truth" not in df_input.columns:
            st.error("Le CSV doit contenir les colonnes 'question' et 'ground_truth'.")
            st.stop()

        questions = df_input["question"].tolist()
        ground_truths = df_input["ground_truth"].tolist()
        n = len(questions)

        st.info(f"Évaluation de {n} question(s) — cela peut prendre quelques minutes…")
        progress_bar = st.progress(0, text="Préparation…")

        # Define retrieve and answer functions for current user/key
        def _eval_retrieve(q: str) -> list[dict]:
            return hybrid_retrieve(q, k=5, use_reranker=False, user_id=user_id)

        def _eval_answer(q: str, context: str) -> str:
            return get_answer_non_streaming(q, context, openai_key)

        try:
            from backend.rag.evaluation import evaluate_rag

            progress_bar.progress(0.2, text="Récupération des contextes et génération des réponses…")
            results = evaluate_rag(
                questions=questions,
                ground_truths=ground_truths,
                retrieve_fn=_eval_retrieve,
                answer_fn=_eval_answer,
                openai_api_key=openai_key,
            )
            progress_bar.progress(1.0, text="Évaluation terminée !")
        except Exception as exc:
            progress_bar.empty()
            st.error(f"❌ Erreur lors de l'évaluation RAGAS : {exc}")
            st.stop()

        means = results["means"]
        per_q = results["per_question"]

        st.markdown("### Résultats agrégés")
        metric_labels = {
            "faithfulness": "Fidélité",
            "answer_relevancy": "Pertinence réponse",
            "context_precision": "Précision contexte",
            "context_recall": "Rappel contexte",
        }
        cols = st.columns(4)
        for col, (metric_key, metric_label) in zip(cols, metric_labels.items()):
            score = means.get(metric_key, float("nan"))
            color = _score_color(score)
            score_str = f"{score:.2%}" if not math.isnan(score) else "N/A"
            col.markdown(
                f"""
                <div style="border-radius:10px; padding:16px; background:{color}22; border:2px solid {color}; text-align:center;">
                    <div style="font-size:1.8em; font-weight:bold; color:{color};">{score_str}</div>
                    <div style="font-size:0.9em; color:#555;">{metric_label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("### Détail par question")
        import pandas as pd

        rows_display = []
        for r in per_q:
            row_d = {
                "Question": r["question"],
                "Réponse générée": r["answer"],
                "Vérité terrain": r["ground_truth"],
                "Fidélité": round(r["faithfulness"], 3) if not math.isnan(r["faithfulness"]) else None,
                "Pertinence": round(r["answer_relevancy"], 3) if not math.isnan(r["answer_relevancy"]) else None,
                "Précision ctx": round(r["context_precision"], 3) if not math.isnan(r["context_precision"]) else None,
                "Rappel ctx": round(r["context_recall"], 3) if not math.isnan(r["context_recall"]) else None,
            }
            rows_display.append(row_d)

        df_results = pd.DataFrame(rows_display)
        st.dataframe(df_results, use_container_width=True)

        # Export
        csv_export = df_results.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📤 Exporter les résultats (CSV)",
            data=csv_export,
            file_name=f"ragas_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )


# ===========================================================================
# TAB 3 — Historique
# ===========================================================================

with tab_history:
    st.subheader("🗂️ Historique des conversations")

    db = _get_conversation_db()

    # New conversation button
    col_new, col_spacer = st.columns([1, 3])
    with col_new:
        if st.button("🆕 Nouvelle conversation"):
            st.session_state.current_conversation_id = None
            st.session_state.current_conversation_title = "Nouvelle conversation"
            st.session_state.chat_history = []
            st.session_state.history_selected_conv = None
            st.success("Nouvelle conversation démarrée. Posez une question dans l'onglet Chat.")

    st.divider()

    conversations = db.list_conversations(user_id)

    if not conversations:
        st.info("Aucune conversation enregistrée pour ce compte. Commencez à discuter dans l'onglet Chat !")
    else:
        # Conversation viewer state
        selected_conv_id = st.session_state.history_selected_conv

        for conv in conversations:
            conv_id = conv["id"]
            title = conv["title"]
            msg_count = conv["message_count"]
            updated = conv["updated_at"][:16].replace("T", " ") if conv["updated_at"] else "—"

            with st.expander(f"**{title}** · {msg_count} msg · {updated}"):
                col_view, col_export, col_delete = st.columns([2, 1, 1])

                with col_view:
                    if st.button("👁️ Voir", key=f"view_{conv_id}"):
                        st.session_state.history_selected_conv = conv_id

                with col_export:
                    export_data = db.export_conversation(conv_id)
                    st.download_button(
                        label="📥 JSON",
                        data=json.dumps(export_data, ensure_ascii=False, indent=2),
                        file_name=f"conv_{conv_id[:8]}.json",
                        mime="application/json",
                        key=f"export_{conv_id}",
                    )

                with col_delete:
                    if st.button("🗑️ Supprimer", key=f"delete_{conv_id}", type="secondary"):
                        db.delete_conversation(conv_id)
                        if st.session_state.current_conversation_id == conv_id:
                            st.session_state.current_conversation_id = None
                            st.session_state.current_conversation_title = "Nouvelle conversation"
                            st.session_state.chat_history = []
                        if st.session_state.history_selected_conv == conv_id:
                            st.session_state.history_selected_conv = None
                        st.rerun()

        # Display selected conversation messages
        if st.session_state.history_selected_conv:
            sel_id = st.session_state.history_selected_conv
            sel_conv = next((c for c in conversations if c["id"] == sel_id), None)
            if sel_conv:
                st.divider()
                st.markdown(f"### 💬 {sel_conv['title']}")
                messages = db.get_messages(sel_id)
                if not messages:
                    st.info("Aucun message dans cette conversation.")
                for msg in messages:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
                        if msg["role"] == "assistant" and msg.get("sources"):
                            with st.expander("📚 Sources"):
                                for src in msg["sources"]:
                                    st.markdown(
                                        f"**{src.get('source', '?')} — page {src.get('page', '?')}**"
                                    )
                                    st.caption(src.get("text", ""))
                                    st.divider()

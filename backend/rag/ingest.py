"""
Document ingestion pipeline:
  File → text extraction → chunking → embedding → Qdrant indexing

Supported formats:
  .pdf   — PyPDFLoader
  .docx  — Docx2txtLoader
  .txt   — TextLoader (utf-8)
  .md    — TextLoader (utf-8)  [UnstructuredMarkdownLoader is too heavy]

Also maintains a per-user BM25 corpus persisted to /data/bm25/<user_id>.pkl.
"""
from __future__ import annotations

import hashlib
import logging
import os
import pickle
import re
import uuid
from pathlib import Path
from typing import Any

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from .config import (
    BM25_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    QDRANT_API_KEY,
    QDRANT_COLLECTION,
    QDRANT_URL,
    bm25_file,
)

logger = logging.getLogger(__name__)

# Supported file extensions
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# ---------------------------------------------------------------------------
# Shared singletons (lazy initialisation)
# ---------------------------------------------------------------------------

_embeddings: HuggingFaceEmbeddings | None = None
_qdrant_client: QdrantClient | None = None

# Per-user in-memory BM25 corpora:  {user_id: list[dict]}
_bm25_corpora: dict[str, list[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Collection name helpers
# ---------------------------------------------------------------------------


def sanitize_collection_name(user_id: str) -> str:
    """
    Return a safe Qdrant collection name for the given user_id.

    Rules: lowercase, replace non-alphanumeric with '_', prefix 'rag_', max 40 chars.
    """
    safe = re.sub(r"[^a-zA-Z0-9]", "_", user_id).lower()
    name = f"rag_{safe}"
    return name[:40]


def _collection_for_user(user_id: str) -> str:
    """Convenience alias used in this module."""
    return sanitize_collection_name(user_id)


# ---------------------------------------------------------------------------
# Singleton accessors
# ---------------------------------------------------------------------------


def get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings


def get_qdrant_client(qdrant_url: str = QDRANT_URL) -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        if QDRANT_API_KEY:
            _qdrant_client = QdrantClient(url=qdrant_url, api_key=QDRANT_API_KEY)
        else:
            _qdrant_client = QdrantClient(url=qdrant_url)
    return _qdrant_client


# ---------------------------------------------------------------------------
# Collection management
# ---------------------------------------------------------------------------


def ensure_collection(client: QdrantClient, collection_name: str = QDRANT_COLLECTION) -> None:
    """Create the Qdrant collection if it does not exist yet."""
    existing = [c.name for c in client.get_collections().collections]
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )
        logger.info("Collection '%s' created.", collection_name)


# ---------------------------------------------------------------------------
# Per-user BM25 corpus management
# ---------------------------------------------------------------------------


def _ensure_bm25_dir() -> None:
    """Create the BM25 directory if it doesn't exist."""
    Path(BM25_DIR).mkdir(parents=True, exist_ok=True)


def load_bm25_corpus(user_id: str = "default") -> list[dict[str, Any]]:
    """
    Load and return the BM25 corpus for the given user.
    Loads from disk on first call; subsequent calls use in-memory cache.
    """
    global _bm25_corpora
    if user_id in _bm25_corpora:
        return _bm25_corpora[user_id]

    corpus: list[dict[str, Any]] = []
    pkl_path = bm25_file(user_id)
    if Path(pkl_path).exists():
        try:
            with open(pkl_path, "rb") as fh:
                corpus = pickle.load(fh)
            logger.info(
                "Loaded BM25 corpus for user '%s' with %d chunks.", user_id, len(corpus)
            )
        except Exception as exc:
            logger.warning("Could not load BM25 corpus for user '%s': %s", user_id, exc)
            corpus = []

    _bm25_corpora[user_id] = corpus
    return corpus


def save_bm25_corpus(user_id: str = "default") -> None:
    """Persist the in-memory BM25 corpus for user_id to disk."""
    _ensure_bm25_dir()
    corpus = _bm25_corpora.get(user_id, [])
    pkl_path = bm25_file(user_id)
    try:
        with open(pkl_path, "wb") as fh:
            pickle.dump(corpus, fh)
    except Exception as exc:
        logger.warning("Could not save BM25 corpus for user '%s': %s", user_id, exc)


def reset_bm25_corpus(user_id: str = "default") -> None:
    """Clear in-memory and on-disk BM25 corpus for a user."""
    global _bm25_corpora
    _bm25_corpora[user_id] = []
    pkl_path = bm25_file(user_id)
    if Path(pkl_path).exists():
        os.remove(pkl_path)


# ---------------------------------------------------------------------------
# Loader selection by extension
# ---------------------------------------------------------------------------


def _load_documents(file_path: str, ext: str):
    """
    Load a document using the appropriate loader for the file extension.
    Returns a list of LangChain Document objects.
    """
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
            f"Formats acceptés : {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return loader.load()


# ---------------------------------------------------------------------------
# Main ingestion function (per-user)
# ---------------------------------------------------------------------------


def ingest_file(
    file_path: str,
    source_name: str,
    user_id: str = "default",
    qdrant_url: str = QDRANT_URL,
) -> int:
    """
    Ingest a document file into the user's Qdrant collection (dense) and
    their BM25 corpus (sparse).

    Supported formats: PDF, DOCX, TXT, MD.

    Returns the number of chunks indexed.
    """
    global _bm25_corpora

    collection_name = _collection_for_user(user_id)

    # Ensure corpus is loaded
    load_bm25_corpus(user_id)

    # Determine extension
    ext = Path(source_name).suffix.lower()
    if not ext:
        ext = Path(file_path).suffix.lower()

    # 1. Load document
    pages = _load_documents(file_path, ext)
    logger.info("Loaded %d page(s)/section(s) from '%s'.", len(pages), source_name)

    # 2. Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    docs = splitter.split_documents(pages)

    # 3. Enrich metadata
    doc_hash = hashlib.md5(source_name.encode()).hexdigest()[:8]
    for i, doc in enumerate(docs):
        doc.metadata["source"] = source_name
        doc.metadata["chunk_id"] = f"{doc_hash}_{i}"
        # PyPDFLoader sets 'page' (0-indexed) — convert to 1-indexed
        if "page" in doc.metadata:
            doc.metadata["page"] = int(doc.metadata["page"]) + 1
        else:
            doc.metadata["page"] = 1

    # 4. Embed & store in user's Qdrant collection
    embeddings = get_embeddings()
    client = get_qdrant_client(qdrant_url)
    ensure_collection(client, collection_name)

    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )
    vector_store.add_documents(docs)

    # 5. Store in user's BM25 corpus
    corpus = _bm25_corpora.setdefault(user_id, [])
    for doc in docs:
        corpus.append(
            {
                "id": doc.metadata["chunk_id"],
                "text": doc.page_content,
                "metadata": doc.metadata,
            }
        )

    save_bm25_corpus(user_id)
    logger.info(
        "Indexed %d chunks from '%s' for user '%s' (collection '%s'). BM25 size: %d.",
        len(docs),
        source_name,
        user_id,
        collection_name,
        len(corpus),
    )
    return len(docs)


# ---------------------------------------------------------------------------
# Helper functions for user collections
# ---------------------------------------------------------------------------


def get_indexed_doc_count(qdrant_url: str = QDRANT_URL, collection_name: str = QDRANT_COLLECTION) -> int:
    """Return total number of vectors in the given collection."""
    try:
        client = get_qdrant_client(qdrant_url)
        existing = [c.name for c in client.get_collections().collections]
        if collection_name not in existing:
            return 0
        info = client.get_collection(collection_name)
        return info.points_count or 0
    except Exception:
        return 0


def get_all_collections(qdrant_url: str = QDRANT_URL) -> dict[str, int]:
    """Return a dict of {collection_name: vector_count} for all collections."""
    try:
        client = get_qdrant_client(qdrant_url)
        collections = client.get_collections().collections
        result = {}
        for col in collections:
            try:
                info = client.get_collection(col.name)
                result[col.name] = info.points_count or 0
            except Exception:
                result[col.name] = 0
        return result
    except Exception:
        return {}


def reset_collection(qdrant_url: str = QDRANT_URL, user_id: str = "default") -> None:
    """Delete and recreate the user's Qdrant collection, and reset their BM25 corpus."""
    collection_name = _collection_for_user(user_id)
    client = get_qdrant_client(qdrant_url)
    existing = [c.name for c in client.get_collections().collections]
    if collection_name in existing:
        client.delete_collection(collection_name)
    ensure_collection(client, collection_name)
    reset_bm25_corpus(user_id)
    logger.info("Collection '%s' reset for user '%s'.", collection_name, user_id)


# ---------------------------------------------------------------------------
# Legacy aliases (kept for backwards compatibility)
# ---------------------------------------------------------------------------


def ingest_pdf(
    file_path: str,
    source_name: str,
    qdrant_url: str = QDRANT_URL,
) -> int:
    """Alias for ingest_file — retained for backwards compatibility."""
    return ingest_file(file_path, source_name, qdrant_url=qdrant_url)

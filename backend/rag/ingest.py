"""
Document ingestion pipeline:
  File → text extraction → chunking → embedding → Qdrant indexing

Supported formats:
  .pdf   — PyPDFLoader
  .docx  — Docx2txtLoader
  .txt   — TextLoader (utf-8)
  .md    — TextLoader (utf-8)  [UnstructuredMarkdownLoader is too heavy]

Also maintains an in-memory BM25 corpus for sparse retrieval.
"""
from __future__ import annotations

import hashlib
import logging
import os
import pickle
import uuid
from pathlib import Path
from typing import Any

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from .config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    QDRANT_API_KEY,
    QDRANT_COLLECTION,
    QDRANT_URL,
)

logger = logging.getLogger(__name__)

# Supported file extensions
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# ---------------------------------------------------------------------------
# Shared singletons (lazy initialisation)
# ---------------------------------------------------------------------------

_embeddings: HuggingFaceEmbeddings | None = None
_qdrant_client: QdrantClient | None = None

# In-memory BM25 corpus:  list of dicts {"id": str, "text": str, "metadata": dict}
_bm25_corpus: list[dict[str, Any]] = []

# Persistent path for the BM25 corpus alongside the service
_BM25_CORPUS_FILE = os.getenv("BM25_CORPUS_FILE", "/tmp/bm25_corpus.pkl")


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


def ensure_collection(client: QdrantClient) -> None:
    """Create the Qdrant collection if it does not exist yet."""
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )
        logger.info("Collection '%s' created.", QDRANT_COLLECTION)


def load_bm25_corpus() -> list[dict[str, Any]]:
    """Load BM25 corpus from disk (if present)."""
    global _bm25_corpus
    if _bm25_corpus:
        return _bm25_corpus
    if Path(_BM25_CORPUS_FILE).exists():
        with open(_BM25_CORPUS_FILE, "rb") as fh:
            _bm25_corpus = pickle.load(fh)
        logger.info("Loaded BM25 corpus with %d chunks.", len(_bm25_corpus))
    return _bm25_corpus


def save_bm25_corpus() -> None:
    with open(_BM25_CORPUS_FILE, "wb") as fh:
        pickle.dump(_bm25_corpus, fh)


def reset_bm25_corpus() -> None:
    global _bm25_corpus
    _bm25_corpus = []
    if Path(_BM25_CORPUS_FILE).exists():
        os.remove(_BM25_CORPUS_FILE)


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
# Main ingestion function
# ---------------------------------------------------------------------------


def ingest_file(
    file_path: str,
    source_name: str,
    qdrant_url: str = QDRANT_URL,
) -> int:
    """
    Ingest a document file into Qdrant (dense) and the BM25 corpus (sparse).

    Supported formats: PDF, DOCX, TXT, MD.

    Returns the number of chunks indexed.
    """
    global _bm25_corpus

    # Ensure corpus is loaded
    load_bm25_corpus()

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

    # 4. Embed & store in Qdrant
    embeddings = get_embeddings()
    client = get_qdrant_client(qdrant_url)
    ensure_collection(client)

    vector_store = QdrantVectorStore(
        client=client,
        collection_name=QDRANT_COLLECTION,
        embedding=embeddings,
    )
    vector_store.add_documents(docs)

    # 5. Store in BM25 corpus
    for doc in docs:
        _bm25_corpus.append(
            {
                "id": doc.metadata["chunk_id"],
                "text": doc.page_content,
                "metadata": doc.metadata,
            }
        )

    save_bm25_corpus()
    logger.info(
        "Indexed %d chunks from '%s'. BM25 corpus size: %d.",
        len(docs),
        source_name,
        len(_bm25_corpus),
    )
    return len(docs)


# ---------------------------------------------------------------------------
# Legacy alias (kept for backwards compatibility)
# ---------------------------------------------------------------------------


def ingest_pdf(
    file_path: str,
    source_name: str,
    qdrant_url: str = QDRANT_URL,
) -> int:
    """Alias for ingest_file — retained for backwards compatibility."""
    return ingest_file(file_path, source_name, qdrant_url)


def get_indexed_doc_count(qdrant_url: str = QDRANT_URL) -> int:
    """Return total number of vectors in the collection."""
    try:
        client = get_qdrant_client(qdrant_url)
        existing = [c.name for c in client.get_collections().collections]
        if QDRANT_COLLECTION not in existing:
            return 0
        info = client.get_collection(QDRANT_COLLECTION)
        return info.points_count or 0
    except Exception:
        return 0


def reset_collection(qdrant_url: str = QDRANT_URL) -> None:
    """Delete and recreate the Qdrant collection, and reset BM25 corpus."""
    client = get_qdrant_client(qdrant_url)
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION in existing:
        client.delete_collection(QDRANT_COLLECTION)
    ensure_collection(client)
    reset_bm25_corpus()
    logger.info("Collection '%s' reset.", QDRANT_COLLECTION)

"""Upsert KB partagé — embedding + écriture Qdrant pour les connecteurs L2bis.

Factorise le code commun aux 4 connecteurs (BOSS, DSN-info, URSSAF, service-public)
pour transformer une liste de KBChunk en points Qdrant dans la collection
partagée `knowledge_base`.

Réutilise les helpers existants (get_embeddings, get_qdrant_client, ensure_collection)
de `rag.ingest` pour ne pas dupliquer la configuration BAAI/bge-m3.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Iterable

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore

from ..config import KNOWLEDGE_BASE_COLLECTION, QDRANT_URL
from ..ingest import (
    CHUNKER_VERSION,
    ensure_collection,
    get_embeddings,
    get_qdrant_client,
)
from .base import KBChunk

logger = logging.getLogger(__name__)


def _stable_chunk_id(source: str, source_id: str, page: str | int, position: int) -> str:
    """Identifiant stable d'un chunk (déterministe pour idempotence)."""
    raw = f"{source}::{source_id}::{page}::{position}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def upsert_kb_chunks(
    chunks: Iterable[KBChunk],
    *,
    qdrant_url: str = QDRANT_URL,
    collection_name: str = KNOWLEDGE_BASE_COLLECTION,
) -> int:
    """Embed + upsert d'une liste de KBChunk dans la collection KB partagée.

    Renvoie le nombre de chunks effectivement upsertés.

    Le chunk_id est dérivé de (source, source_id, page, position) — stable, donc
    relancer l'upsert remplace les anciens vecteurs au lieu de dupliquer (à
    condition que Qdrant utilise le chunk_id comme point id, ce qui n'est pas
    le cas ici via QdrantVectorStore — pour l'instant on tolère une duplication
    minime en cas de re-run, à corriger en L2bis suivant si nécessaire).
    """
    chunks_list = list(chunks)
    if not chunks_list:
        return 0

    docs: list[Document] = []
    counters: dict[str, int] = {}
    for chunk in chunks_list:
        meta = dict(chunk.metadata)
        source = meta.get("source", "unknown")
        source_id = meta.get("source_id", "?")
        page = meta.get("page", "?")
        key = f"{source}::{source_id}"
        position = counters.get(key, 0)
        counters[key] = position + 1

        meta.setdefault("chunker_version", CHUNKER_VERSION)
        meta["chunk_id"] = _stable_chunk_id(source, str(source_id), page, position)
        meta["chunk_position"] = position
        docs.append(Document(page_content=chunk.text, metadata=meta))

    embeddings = get_embeddings()
    client = get_qdrant_client(qdrant_url)
    ensure_collection(client, collection_name)
    store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )
    store.add_documents(docs)
    logger.info(
        "Upserted %d chunks into KB collection '%s'", len(docs), collection_name
    )
    return len(docs)

"""Upsert KB partagé — embedding + écriture Qdrant pour les connecteurs L2bis.

Factorise le code commun aux 4 connecteurs (BOSS, DSN-info, URSSAF, service-public)
pour transformer une liste de KBChunk en points Qdrant dans la collection
partagée `knowledge_base`.

Réutilise les helpers existants (get_embeddings, get_qdrant_client, ensure_collection)
de `rag.ingest` pour ne pas dupliquer la configuration BAAI/bge-m3.

Hardening (Lot 2bis) :
- on filtre les chunks vides ou trop courts (< MIN_CHUNK_CHARS) pour éviter
  d'embedder du bruit (pages d'erreur quasi vides, fragments isolés).
- on tronque les chunks en caractères avant embedding (UPSERT_MAX_CHARS),
  borne haute complémentaire à la troncation tokenizer côté bge-m3.
- on traite l'upsert en sous-lots (UPSERT_BATCH) avec un log de progression
  pour éviter le silence radio si le pipeline bloque sur un chunk.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
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

MIN_CHUNK_CHARS: int = int(os.getenv("KB_MIN_CHUNK_CHARS", "50"))
UPSERT_MAX_CHARS: int = int(os.getenv("KB_UPSERT_MAX_CHARS", "12000"))
UPSERT_BATCH: int = int(os.getenv("KB_UPSERT_BATCH", "16"))


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
        logger.info("upsert_kb_chunks: aucun chunk à indexer")
        return 0

    docs: list[Document] = []
    counters: dict[str, int] = {}
    skipped_short = 0
    truncated = 0
    source_label = "unknown"

    for chunk in chunks_list:
        text = chunk.text or ""
        text_stripped = text.strip()
        if len(text_stripped) < MIN_CHUNK_CHARS:
            skipped_short += 1
            continue

        # Borne haute en caractères avant embedding (ceinture en plus de la
        # troncation tokenizer côté SentenceTransformer.max_seq_length).
        if len(text_stripped) > UPSERT_MAX_CHARS:
            text_stripped = text_stripped[:UPSERT_MAX_CHARS]
            truncated += 1

        meta = dict(chunk.metadata)
        source = meta.get("source", "unknown")
        source_label = source
        source_id = meta.get("source_id", "?")
        page = meta.get("page", "?")
        key = f"{source}::{source_id}"
        position = counters.get(key, 0)
        counters[key] = position + 1

        meta.setdefault("chunker_version", CHUNKER_VERSION)
        meta["chunk_id"] = _stable_chunk_id(source, str(source_id), page, position)
        meta["chunk_position"] = position
        docs.append(Document(page_content=text_stripped, metadata=meta))

    total = len(docs)
    if skipped_short:
        logger.info(
            "[%s] %d chunks trop courts (<%d chars) ignorés avant embedding",
            source_label, skipped_short, MIN_CHUNK_CHARS,
        )
    if truncated:
        logger.info(
            "[%s] %d chunks tronqués à %d caractères avant embedding",
            source_label, truncated, UPSERT_MAX_CHARS,
        )
    if total == 0:
        logger.info("[%s] aucun chunk à embedder après filtrage", source_label)
        return 0

    logger.info(
        "[%s] début embedding/upsert : %d chunks, batch=%d",
        source_label, total, UPSERT_BATCH,
    )

    embeddings = get_embeddings()
    client = get_qdrant_client(qdrant_url)
    ensure_collection(client, collection_name)
    store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )

    upserted = 0
    t_start = time.monotonic()
    for batch_start in range(0, total, UPSERT_BATCH):
        batch_end = min(batch_start + UPSERT_BATCH, total)
        batch = docs[batch_start:batch_end]
        sizes = [len(d.page_content) for d in batch]
        logger.info(
            "[%s] embedding+upsert chunks %d-%d/%d (tailles min=%d max=%d moy=%d)",
            source_label,
            batch_start + 1,
            batch_end,
            total,
            min(sizes),
            max(sizes),
            sum(sizes) // len(sizes),
        )
        t_batch = time.monotonic()
        try:
            store.add_documents(batch)
        except Exception as exc:
            logger.error(
                "[%s] échec embedding/upsert batch %d-%d: %s",
                source_label, batch_start + 1, batch_end, exc,
            )
            raise
        upserted += len(batch)
        logger.info(
            "[%s] batch %d-%d/%d upserté en %.1fs (cumul %d/%d)",
            source_label,
            batch_start + 1,
            batch_end,
            total,
            time.monotonic() - t_batch,
            upserted,
            total,
        )

    logger.info(
        "[%s] upsert KB terminé : %d chunks dans '%s' en %.1fs",
        source_label, upserted, collection_name, time.monotonic() - t_start,
    )
    return upserted

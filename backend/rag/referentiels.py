"""
Référentiels Opsidium — méthodologie interne, grilles d'analyse, templates.

Ces documents alimentent UNIQUEMENT le pipeline d'analyse CDC client (gap-analysis).
Ils ne sont pas exposés au chat « Tell me ».

Architecture :
    - Collection Qdrant dédiée : `referentiels_opsidium`
    - Formats acceptés : PDF, DOCX, XLSX, XLS
    - Accès : admin only (contrôlé côté FastAPI via require_admin)
    - Pas de BM25 sparse pour cette collection (volumétrie faible, dense suffit
      pour combiner avec le retrieval CDC client en gap-analysis)
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from langchain_qdrant import QdrantVectorStore
from qdrant_client.http import models as qmodels

from .config import EMBEDDING_DIM, QDRANT_URL
from .ingest import (
    _load_documents,
    _load_excel_document,
    ensure_collection,
    get_embeddings,
    get_qdrant_client,
)
from .semantic_chunker import (
    CHUNKER_VERSION,
    semantic_chunk_documents,
)

logger = logging.getLogger(__name__)


REFERENTIELS_COLLECTION: str = os.getenv(
    "REFERENTIELS_COLLECTION", "referentiels_opsidium"
)

#: Format attendu côté client. On reste strict pour éviter d'embarquer du HTML
#: ou des fichiers texte mal formés dans une collection « doctrine interne ».
SUPPORTED_REFERENTIEL_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls"}


def _ensure_referentiels_collection() -> None:
    """Crée la collection `referentiels_opsidium` si elle n'existe pas."""
    client = get_qdrant_client(QDRANT_URL)
    ensure_collection(client, REFERENTIELS_COLLECTION)


def ingest_referentiel(file_path: str, source_name: str) -> dict[str, Any]:
    """Ingère un référentiel (PDF, DOCX, XLSX, XLS) dans la collection partagée.

    Args:
        file_path: chemin local vers le fichier (déjà uploadé)
        source_name: nom logique affiché à l'utilisateur (ex: "Grille analyse v3.docx")

    Returns:
        dict avec `source`, `chunks`, `chunker_version`.
    """
    ext = Path(source_name).suffix.lower()
    if not ext:
        ext = Path(file_path).suffix.lower()

    if ext not in SUPPORTED_REFERENTIEL_EXTENSIONS:
        raise ValueError(
            f"Format non supporté : '{ext}'. "
            f"Formats acceptés : {', '.join(sorted(SUPPORTED_REFERENTIEL_EXTENSIONS))}"
        )

    # 1. Charger le document
    if ext in {".xlsx", ".xls"}:
        pages = _load_excel_document(file_path, ext, source_name)
    else:
        pages = _load_documents(file_path, ext)
    logger.info(
        "[referentiels] Chargé %d page(s)/section(s) depuis '%s'.",
        len(pages),
        source_name,
    )

    # 2. Chunking sémantique (même pipeline que le reste de l'app)
    embeddings = get_embeddings()
    docs = semantic_chunk_documents(pages, embeddings.embed_documents)

    # 3. Métadonnées
    doc_hash = hashlib.md5(source_name.encode()).hexdigest()[:8]
    for i, doc in enumerate(docs):
        doc.metadata["source"] = source_name
        doc.metadata["scope"] = "referentiel"
        doc.metadata["chunk_id"] = f"ref_{doc_hash}_{i}"
        if "page" in doc.metadata:
            doc.metadata["page"] = int(doc.metadata["page"]) + 1
        else:
            doc.metadata["page"] = 1
        doc.metadata.setdefault("chunker_version", CHUNKER_VERSION)

    # 4. Embed + upsert
    _ensure_referentiels_collection()
    client = get_qdrant_client(QDRANT_URL)
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=REFERENTIELS_COLLECTION,
        embedding=embeddings,
    )
    vector_store.add_documents(docs)

    # v3.10.0 : invalider le cache BM25 référentiels (sera reconstruit au
    # prochain appel du ReferentielsOnlyRetriever).
    try:
        from .retriever import reset_referentiels_bm25_cache
        reset_referentiels_bm25_cache()
    except Exception:  # pragma: no cover — défensif
        pass

    logger.info(
        "[referentiels] Indexé %d chunks depuis '%s' (collection '%s').",
        len(docs),
        source_name,
        REFERENTIELS_COLLECTION,
    )
    return {
        "source": source_name,
        "chunks": len(docs),
        "chunker_version": CHUNKER_VERSION,
    }


def list_referentiels() -> list[dict[str, Any]]:
    """Retourne la liste des référentiels indexés (groupés par source).

    Chaque item : {"source": str, "chunks": int}.
    """
    counts: dict[str, int] = {}
    try:
        client = get_qdrant_client(QDRANT_URL)
        existing = {c.name for c in client.get_collections().collections}
        if REFERENTIELS_COLLECTION not in existing:
            return []
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=REFERENTIELS_COLLECTION,
                limit=256,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            for p in points:
                payload = p.payload or {}
                meta = payload.get("metadata", {}) or {}
                src = meta.get("source") or payload.get("source") or "unknown"
                counts[src] = counts.get(src, 0) + 1
            if offset is None:
                break
    except Exception as exc:
        logger.warning("[referentiels] scroll failed: %s", exc)
        return []

    return [
        {"source": s, "chunks": c}
        for s, c in sorted(counts.items())
    ]


def delete_referentiel(source: str) -> dict[str, Any]:
    """Supprime tous les chunks d'un référentiel (filtre `metadata.source`)."""
    client = get_qdrant_client(QDRANT_URL)
    existing = {c.name for c in client.get_collections().collections}
    if REFERENTIELS_COLLECTION not in existing:
        return {"source": source, "deleted": 0}

    flt = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="metadata.source",
                match=qmodels.MatchValue(value=source),
            )
        ]
    )
    try:
        count_resp = client.count(
            collection_name=REFERENTIELS_COLLECTION,
            count_filter=flt,
            exact=True,
        )
        deleted = int(count_resp.count)
    except Exception as exc:
        logger.warning("[referentiels] count failed for '%s': %s", source, exc)
        deleted = 0

    try:
        client.delete(
            collection_name=REFERENTIELS_COLLECTION,
            points_selector=qmodels.FilterSelector(filter=flt),
            wait=True,
        )
    except Exception as exc:
        logger.error("[referentiels] delete failed for '%s': %s", source, exc)
        raise

    # v3.10.0 : invalider le cache BM25 référentiels.
    try:
        from .retriever import reset_referentiels_bm25_cache
        reset_referentiels_bm25_cache()
    except Exception:  # pragma: no cover — défensif
        pass

    logger.info(
        "[referentiels] Supprimé %d chunks pour '%s'.",
        deleted,
        source,
    )
    return {"source": source, "deleted": deleted}


def get_referentiels_info() -> dict[str, Any]:
    """Renvoie un résumé : collection, nombre total de vecteurs, nombre de docs."""
    vectors_count = 0
    docs_count = 0
    exists = False
    try:
        client = get_qdrant_client(QDRANT_URL)
        existing = {c.name for c in client.get_collections().collections}
        exists = REFERENTIELS_COLLECTION in existing
        if exists:
            info = client.get_collection(REFERENTIELS_COLLECTION)
            vectors_count = int(getattr(info, "points_count", 0) or 0)
            docs_count = len(list_referentiels())
    except Exception as exc:
        logger.warning("[referentiels] info failed: %s", exc)

    return {
        "collection": REFERENTIELS_COLLECTION,
        "exists": exists,
        "vectors_count": vectors_count,
        "documents_count": docs_count,
        "embedding_dim": EMBEDDING_DIM,
    }

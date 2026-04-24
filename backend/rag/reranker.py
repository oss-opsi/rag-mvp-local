"""
Cross-encoder reranker using BAAI/bge-reranker-base.

Singleton pattern: the model is loaded lazily on first use to avoid
blocking the application at import time.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_RERANKER_MODEL = "BAAI/bge-reranker-base"

# Singleton instance
_cross_encoder = None


def _get_cross_encoder():
    """Lazy-load and return the CrossEncoder singleton."""
    global _cross_encoder
    if _cross_encoder is None:
        from sentence_transformers import CrossEncoder

        logger.info("Loading cross-encoder model '%s'…", _RERANKER_MODEL)
        _cross_encoder = CrossEncoder(_RERANKER_MODEL)
        logger.info("Cross-encoder model loaded.")
    return _cross_encoder


class CrossEncoderReranker:
    """
    Reranks a list of retrieved chunks using a cross-encoder model.

    Usage:
        reranker = CrossEncoderReranker()
        top_docs = reranker.rerank(query, docs, top_n=5)
    """

    def rerank(
        self,
        query: str,
        docs: list[dict[str, Any]],
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Score (query, doc.text) pairs with the cross-encoder, sort descending,
        and return the top_n docs.  Each returned doc has an extra
        ``metadata["rerank_score"]`` field containing the cross-encoder score.

        Parameters
        ----------
        query:  The user question.
        docs:   List of chunk dicts as returned by HybridRetriever.retrieve()
                (keys: "text", "metadata", "rrf_score").
        top_n:  Number of docs to return after reranking.
        """
        if not docs:
            return []

        cross_encoder = _get_cross_encoder()

        # Build (query, passage) pairs
        pairs = [(query, doc["text"]) for doc in docs]

        # Score all pairs — returns a numpy array of floats
        scores = cross_encoder.predict(pairs)

        # Attach score to each doc (copy metadata to avoid mutating the original)
        scored = []
        for doc, score in zip(docs, scores):
            enriched = dict(doc)
            enriched["metadata"] = dict(doc["metadata"])
            enriched["metadata"]["rerank_score"] = float(score)
            scored.append((float(score), enriched))

        # Sort descending by cross-encoder score
        scored.sort(key=lambda x: x[0], reverse=True)

        return [doc for _, doc in scored[:top_n]]

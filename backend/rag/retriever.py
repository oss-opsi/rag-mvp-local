"""
Hybrid retrieval: Dense (Qdrant COSINE) + Sparse (BM25) fused with RRF.

Reciprocal Rank Fusion:
    score(doc) = Σ_i  1 / (rrf_k + rank_i)

where rrf_k=60 is a constant that dampens the influence of high-rank items,
and the sum is over all retrieval lists in which the document appears.

Optional cross-encoder reranking:
    Pass rerank=True to retrieve() to run a CrossEncoderReranker on top of
    the RRF results.  In that case RRF retrieves top-15 candidates which are
    then narrowed to top-k by the reranker.

Per-user factory:
    Use get_retriever_for_user(user_id) to get a HybridRetriever scoped to
    a specific user's Qdrant collection and BM25 corpus.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore

from .config import (
    EMBEDDING_MODEL,
    KB_RETRIEVAL_ENABLED,
    KNOWLEDGE_BASE_COLLECTION,
    QDRANT_COLLECTION,
    QDRANT_URL,
    RETRIEVAL_K,
    RETRIEVAL_K_DENSE,
    RETRIEVAL_K_SPARSE,
    RRF_K,
)
from .ingest import (
    get_embeddings,
    get_qdrant_client,
    load_bm25_corpus,
    sanitize_collection_name,
)

logger = logging.getLogger(__name__)

# When reranking, retrieve this many RRF candidates before reranking to top-k
_RERANK_CANDIDATE_K = 15


class HybridRetriever:
    """
    Combines dense vector search (Qdrant) and sparse BM25 search,
    then fuses results using Reciprocal Rank Fusion.

    Optionally applies cross-encoder reranking as a second stage.
    """

    def __init__(
        self,
        qdrant_url: str = QDRANT_URL,
        collection_name: str = QDRANT_COLLECTION,
        user_id: str | None = None,
        rrf_k: int = RRF_K,
        include_kb: bool = KB_RETRIEVAL_ENABLED,
        kb_collection: str = KNOWLEDGE_BASE_COLLECTION,
    ) -> None:
        self.qdrant_url = qdrant_url
        self.rrf_k = rrf_k
        # If user_id is provided, derive the collection name from it
        if user_id is not None:
            self.collection_name = sanitize_collection_name(user_id)
            self.user_id = user_id
        else:
            self.collection_name = collection_name
            self.user_id = None
        # Collection partagée « knowledge_base » interrogée en parallèle.
        self.include_kb = include_kb
        self.kb_collection = kb_collection

    # ------------------------------------------------------------------
    # Dense retrieval
    # ------------------------------------------------------------------

    def _dense_search_collection(
        self, query: str, k_dense: int, collection_name: str, scope: str
    ) -> list[tuple[str, dict[str, Any], float]]:
        """
        Recherche dense dans une collection donnée.
        Tague chaque résultat avec scope = 'private' ou 'kb' dans la métadonnée.
        """
        embeddings = get_embeddings()
        client = get_qdrant_client(self.qdrant_url)
        vector_store = QdrantVectorStore(
            client=client,
            collection_name=collection_name,
            embedding=embeddings,
        )
        try:
            results = vector_store.similarity_search_with_score(query, k=k_dense)
        except Exception as exc:
            logger.warning(
                "Dense search failed for collection '%s': %s", collection_name, exc
            )
            return []
        out: list[tuple[str, dict[str, Any], float]] = []
        for doc, score in results:
            meta = dict(doc.metadata or {})
            # Tague la provenance pour pouvoir distinguer dans les citations.
            meta.setdefault("scope", scope)
            meta.setdefault("collection", collection_name)
            out.append((doc.page_content, meta, float(score)))
        return out

    def _dense_search(
        self, query: str, k_dense: int
    ) -> list[tuple[str, dict[str, Any], float]]:
        """
        Recherche dense sur la collection privée + (optionnel) la KB partagée.
        Les résultats sont concaténés puis triés par score descendant ;
        la fusion RRF en aval ré-classe l’ensemble.
        """
        private_results = self._dense_search_collection(
            query, k_dense, self.collection_name, scope="private"
        )
        if not self.include_kb:
            return private_results
        kb_results = self._dense_search_collection(
            query, k_dense, self.kb_collection, scope="kb"
        )
        # Tri par score descendant pour stabilité du rang
        merged = sorted(
            private_results + kb_results, key=lambda r: r[2], reverse=True
        )
        return merged

    # ------------------------------------------------------------------
    # Sparse retrieval (BM25)
    # ------------------------------------------------------------------

    def _sparse_search(
        self, query: str, k_sparse: int
    ) -> list[tuple[str, dict[str, Any], float]]:
        """
        Returns list of (text, metadata, bm25_score) sorted by descending score.
        """
        from rank_bm25 import BM25Okapi

        corpus = load_bm25_corpus(self.user_id or "default")
        if not corpus:
            return []

        tokenized_corpus = [entry["text"].lower().split() for entry in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = query.lower().split()
        scores = bm25.get_scores(tokenized_query)

        # Pair each chunk with its BM25 score
        indexed = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )[:k_sparse]

        return [
            (corpus[i]["text"], corpus[i]["metadata"], float(s))
            for i, s in indexed
            if s > 0  # ignore zero-score docs
        ]

    # ------------------------------------------------------------------
    # RRF fusion
    # ------------------------------------------------------------------

    @staticmethod
    def _rrf_score(rank: int, rrf_k: int) -> float:
        """Reciprocal Rank Fusion score for a single list."""
        return 1.0 / (rrf_k + rank + 1)  # rank is 0-indexed

    def _fuse_rrf(
        self,
        dense_results: list[tuple[str, dict[str, Any], float]],
        sparse_results: list[tuple[str, dict[str, Any], float]],
        k: int,
    ) -> list[dict[str, Any]]:
        """
        Merge dense and sparse results via RRF.

        Uses chunk_id from metadata as the canonical document identifier.
        Falls back to (text[:80]) if chunk_id is absent.
        """
        rrf_scores: dict[str, float] = {}
        doc_store: dict[str, dict[str, Any]] = {}

        def _doc_key(text: str, metadata: dict) -> str:
            return metadata.get("chunk_id", text[:80])

        # Score from dense ranking
        for rank, (text, metadata, _) in enumerate(dense_results):
            key = _doc_key(text, metadata)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + self._rrf_score(
                rank, self.rrf_k
            )
            doc_store[key] = {"text": text, "metadata": metadata}

        # Score from sparse ranking
        for rank, (text, metadata, _) in enumerate(sparse_results):
            key = _doc_key(text, metadata)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + self._rrf_score(
                rank, self.rrf_k
            )
            if key not in doc_store:
                doc_store[key] = {"text": text, "metadata": metadata}

        # Sort by fused RRF score descending
        sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)

        results = []
        for key in sorted_keys[:k]:
            entry = doc_store[key]
            results.append(
                {
                    "text": entry["text"],
                    "metadata": entry["metadata"],
                    "rrf_score": round(rrf_scores[key], 6),
                }
            )
        return results

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        k: int = RETRIEVAL_K,
        k_dense: int = RETRIEVAL_K_DENSE,
        k_sparse: int = RETRIEVAL_K_SPARSE,
        rerank: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Hybrid search: returns top-k chunks ranked by RRF fusion score.

        If rerank=True, retrieves _RERANK_CANDIDATE_K via RRF first, then
        narrows to k using the CrossEncoderReranker.

        Each result is a dict:
            {
                "text":      str,
                "metadata":  dict (source, page, chunk_id, [rerank_score]),
                "rrf_score": float,
            }
        """
        # When reranking we want more RRF candidates to feed the cross-encoder
        rrf_k = _RERANK_CANDIDATE_K if rerank else k

        dense_results = self._dense_search(query, k_dense)
        sparse_results = self._sparse_search(query, k_sparse)

        logger.debug(
            "Dense: %d results, Sparse: %d results.",
            len(dense_results),
            len(sparse_results),
        )

        fused = self._fuse_rrf(dense_results, sparse_results, rrf_k)

        if rerank and fused:
            from .reranker import CrossEncoderReranker

            reranker = CrossEncoderReranker()
            fused = reranker.rerank(query, fused, top_n=k)

        return fused


def get_retriever_for_user(user_id: str, qdrant_url: str = QDRANT_URL) -> HybridRetriever:
    """
    Factory: return a HybridRetriever scoped to the given user's collection
    and BM25 corpus.
    """
    return HybridRetriever(qdrant_url=qdrant_url, user_id=user_id)

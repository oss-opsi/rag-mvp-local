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
from .referentiels import REFERENTIELS_COLLECTION
from .ingest import (
    get_embeddings,
    get_qdrant_client,
    load_bm25_corpus,
    sanitize_collection_name,
)

__all__ = [
    "HybridRetriever",
    "ReferentielsOnlyRetriever",
    "get_retriever_for_user",
]

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
        # Collection partagée « knowledge_base » (sources publiques :
        # service-public, BOSS, DSN-info, URSSAF…) — utilisée par le chat.
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
        Recherche dense sur :
          - la collection privée (Indexation user),
          - la KB partagée (sources publiques) si include_kb.

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

    def retrieve_split(
        self,
        query: str,
        k: int = RETRIEVAL_K,
        k_dense: int = RETRIEVAL_K_DENSE,
        k_sparse: int = RETRIEVAL_K_SPARSE,
        rerank: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Recherche scindée : retourne les chunks classés séparément pour
        la collection privée (Indexation user) et pour la KB publique.

        Chaque liste est triée par score RRF descendant et limitée à ``k``.
        Le but est de pouvoir construire une réponse en deux sections
        distinctes (documents privés / sources publiques).

        Returns:
            {"private": [...], "kb": [...]}
            Une liste peut être vide si la collection ne contient aucun
            résultat pertinent.
        """
        rrf_k = _RERANK_CANDIDATE_K if rerank else k

        # Dense par collection
        private_dense = self._dense_search_collection(
            query, k_dense, self.collection_name, scope="private"
        )
        kb_dense: list[tuple[str, dict[str, Any], float]] = []
        if self.include_kb:
            kb_dense = self._dense_search_collection(
                query, k_dense, self.kb_collection, scope="kb"
            )

        # BM25 ne couvre que la collection privée de l'utilisateur.
        sparse = self._sparse_search(query, k_sparse)

        private_fused = self._fuse_rrf(private_dense, sparse, rrf_k)
        kb_fused = self._fuse_rrf(kb_dense, [], rrf_k)

        if rerank:
            from .reranker import CrossEncoderReranker

            reranker = CrossEncoderReranker()
            if private_fused:
                private_fused = reranker.rerank(query, private_fused, top_n=k)
            if kb_fused:
                kb_fused = reranker.rerank(query, kb_fused, top_n=k)
        else:
            private_fused = private_fused[:k]
            kb_fused = kb_fused[:k]

        return {"private": private_fused, "kb": kb_fused}


class ReferentielsOnlyRetriever:
    """Retriever dédié à l'analyse CDC : interroge UNIQUEMENT la collection
    `referentiels_opsidium` (méthodologie interne Opsidium).

    Cloisonnement strict : ce retriever n'a aucune visibilité sur la
    collection privée de l'utilisateur ni sur la KB publique. Il sert
    exclusivement au pipeline gap-analysis pour évaluer les exigences
    d'un cahier des charges client par rapport à la méthodologie Opsidium.
    """

    def __init__(
        self,
        qdrant_url: str = QDRANT_URL,
        rrf_k: int = RRF_K,
        collection: str = REFERENTIELS_COLLECTION,
    ) -> None:
        self.qdrant_url = qdrant_url
        self.rrf_k = rrf_k
        self.collection = collection

    def _dense_search(
        self, query: str, k_dense: int
    ) -> list[tuple[str, dict[str, Any], float]]:
        embeddings = get_embeddings()
        client = get_qdrant_client(self.qdrant_url)
        # Si la collection n'existe pas encore (aucun référentiel déposé),
        # retourner une liste vide plutôt que de lever une exception.
        try:
            existing = {c.name for c in client.get_collections().collections}
            if self.collection not in existing:
                return []
        except Exception as exc:
            logger.warning(
                "ReferentielsOnlyRetriever: Qdrant unreachable: %s", exc
            )
            return []

        vector_store = QdrantVectorStore(
            client=client,
            collection_name=self.collection,
            embedding=embeddings,
        )
        try:
            results = vector_store.similarity_search_with_score(query, k=k_dense)
        except Exception as exc:
            logger.warning(
                "Dense search failed for collection '%s': %s", self.collection, exc
            )
            return []
        out: list[tuple[str, dict[str, Any], float]] = []
        for doc, score in results:
            meta = dict(doc.metadata or {})
            meta.setdefault("scope", "referentiel")
            meta.setdefault("collection", self.collection)
            out.append((doc.page_content, meta, float(score)))
        return out

    def retrieve(
        self,
        query: str,
        k: int = RETRIEVAL_K,
        k_dense: int = RETRIEVAL_K_DENSE,
        k_sparse: int = RETRIEVAL_K_SPARSE,  # noqa: ARG002 — ignoré (pas de BM25)
        rerank: bool = False,
    ) -> list[dict[str, Any]]:
        """Recherche dense uniquement (pas de BM25 sur les référentiels).

        Le paramètre `k_sparse` est accepté pour compatibilité de signature
        avec `HybridRetriever.retrieve()` mais ignoré.
        """
        rrf_k = _RERANK_CANDIDATE_K if rerank else k
        dense = self._dense_search(query, k_dense)
        if not dense:
            return []

        # Ranking dense direct, format aligné sur HybridRetriever.retrieve()
        ranked: list[dict[str, Any]] = []
        for rank, (text, metadata, score) in enumerate(dense[:rrf_k]):
            ranked.append(
                {
                    "text": text,
                    "metadata": metadata,
                    "rrf_score": round(1.0 / (self.rrf_k + rank + 1), 6),
                    "_dense_score": round(score, 6),
                }
            )

        if rerank and ranked:
            from .reranker import CrossEncoderReranker
            reranker = CrossEncoderReranker()
            ranked = reranker.rerank(query, ranked, top_n=k)
        else:
            ranked = ranked[:k]

        return ranked


def get_retriever_for_user(
    user_id: str,
    qdrant_url: str = QDRANT_URL,
    include_kb: bool | None = None,
) -> HybridRetriever:
    """
    Factory: return a HybridRetriever scoped to the given user's collection
    and BM25 corpus.

    Cloisonnement des sources (Tell me) :
      - Chat « Tell me »  → ce retriever (Indexation user + KB publique)
      - Analyse CDC      → utiliser ReferentielsOnlyRetriever à la place

    Args:
        include_kb: si fourni, force l'inclusion (ou non) de la KB publique.
          Si None, retombe sur le flag global ``KB_RETRIEVAL_ENABLED``.
    """
    kwargs: dict[str, Any] = {
        "qdrant_url": qdrant_url,
        "user_id": user_id,
    }
    if include_kb is not None:
        kwargs["include_kb"] = include_kb
    return HybridRetriever(**kwargs)

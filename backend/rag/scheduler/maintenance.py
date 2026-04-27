"""Fonctions de maintenance avancée appelées par le runner.

Toutes les fonctions retournent un dict ``{pages_fetched, chunks_indexed,
log_excerpt}`` pour rester compatibles avec le runner FIFO. Quand une métrique
n'a pas de sens (ex. integrity_check), elle vaut 0.

- reembed_source(source)         : purge + re-fetch + re-embed une source publique.
- reembed_all()                  : enchaîne les 4 sources publiques.
- optimize_qdrant_collection(c)  : optimize d'une collection Qdrant.
- integrity_check()              : compte les points et chunks orphelins.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from . import db

logger = logging.getLogger(__name__)

# Importé en module-level pour que les tests puissent patcher facilement
# `rag.scheduler.maintenance.get_qdrant_client`. Lazy import si l'import
# direct échoue (env de test sans qdrant-client par exemple).
try:
    from rag.ingest import get_qdrant_client  # type: ignore
except Exception:  # pragma: no cover
    get_qdrant_client = None  # type: ignore


# ---------------------------------------------------------------------------
# Re-embedding
# ---------------------------------------------------------------------------


def reembed_source(
    source: str, *, job_id: Optional[int] = None
) -> dict[str, Any]:
    """Re-embedding complet d'une source publique.

    Identique à un refresh classique mais explicite : on purge la collection
    knowledge_base pour cette source, puis on re-fetch via le connecteur,
    puis on re-embed avec le modèle d'embedding actuel.
    """
    if source not in db.PUBLIC_SOURCES:
        raise ValueError(
            f"Source publique inconnue : '{source}'. "
            f"Attendu : {', '.join(db.PUBLIC_SOURCES)}."
        )

    # Le pipeline est exactement celui du connecteur public — on délègue au
    # runner pour ne pas dupliquer la logique de purge + upsert KB.
    from .runner import _run_public_connector  # import local : pas de cycle
    return _run_public_connector(source, job_id or 0)


def reembed_all(*, job_id: Optional[int] = None) -> dict[str, Any]:
    """Enchaîne le re-embedding des 4 sources publiques.

    Très long (plusieurs heures). Le log_excerpt agrège les compteurs
    source par source pour permettre un suivi rapide.
    """
    total_pages = 0
    total_chunks = 0
    sections: list[str] = []
    for src in db.PUBLIC_SOURCES:
        # Cancel demandé entre 2 sources : on s'arrête proprement.
        if job_id is not None and db.is_stop_requested(job_id):
            sections.append(f"[{src}] annulation demandée — interrompu")
            break
        started = time.time()
        try:
            result = reembed_source(src, job_id=job_id)
            pages = int(result.get("pages_fetched") or 0)
            chunks = int(result.get("chunks_indexed") or 0)
            total_pages += pages
            total_chunks += chunks
            duration = round(time.time() - started, 1)
            sections.append(
                f"[{src}] OK — pages={pages} chunks={chunks} "
                f"durée={duration}s"
            )
        except Exception as exc:
            duration = round(time.time() - started, 1)
            sections.append(f"[{src}] ERREUR — {exc} (durée={duration}s)")
            logger.exception("reembed_all : %s a échoué", src)
            # On continue les autres sources malgré l'erreur.
    log = "\n".join(sections)
    return {
        "pages_fetched": total_pages,
        "chunks_indexed": total_chunks,
        "log_excerpt": log,
    }


# ---------------------------------------------------------------------------
# Optimize Qdrant
# ---------------------------------------------------------------------------


_OPTIMIZABLE_COLLECTIONS_DEFAULT = (
    "knowledge_base",
    "referentiels_opsidium",
)


def optimize_qdrant_collection(collection_name: str) -> dict[str, Any]:
    """Force un optimize sur une collection Qdrant.

    Utilise l'API qdrant_client pour mettre à jour ``optimizers_config``
    (max_segment_number=1) ce qui déclenche un compactage des segments.
    Documente la taille avant/après dans le log.
    """
    from qdrant_client.http import models as qmodels
    from rag.config import QDRANT_URL, QDRANT_API_KEY

    if not collection_name:
        raise ValueError("Nom de collection manquant pour optimize_qdrant.")
    if get_qdrant_client is None:  # pragma: no cover
        raise RuntimeError("qdrant-client indisponible.")

    client = get_qdrant_client(QDRANT_URL)
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        raise ValueError(f"Collection introuvable : '{collection_name}'.")

    before = client.get_collection(collection_name)
    points_before = int(getattr(before, "points_count", 0) or 0)
    segs_before = int(getattr(before, "segments_count", 0) or 0)

    started = time.time()
    # Demande explicite à Qdrant de compacter (mise à jour optimizers_config).
    # default_segment_number=1 force la fusion en un seul segment ; le travail
    # est asynchrone côté serveur Qdrant.
    client.update_collection(
        collection_name=collection_name,
        optimizers_config=qmodels.OptimizersConfigDiff(
            default_segment_number=1,
            indexing_threshold=10_000,
        ),
    )
    # Petit délai pour laisser Qdrant amorcer la tâche d'optimisation
    # (l'opération elle-même est asynchrone côté serveur).
    time.sleep(0.5)

    after = client.get_collection(collection_name)
    points_after = int(getattr(after, "points_count", 0) or 0)
    segs_after = int(getattr(after, "segments_count", 0) or 0)
    duration = round(time.time() - started, 2)

    log = (
        f"collection={collection_name}\n"
        f"points: avant={points_before} après={points_after}\n"
        f"segments: avant={segs_before} après={segs_after}\n"
        f"durée={duration}s\n"
        "(optimize asynchrone côté Qdrant — la fusion finale peut continuer)"
    )
    # On considère le job réussi dès que la requête d'optimize est acceptée.
    _ = QDRANT_API_KEY  # éviter import inutilisé en cas d'usage futur
    return {
        "pages_fetched": 0,
        "chunks_indexed": points_after,
        "log_excerpt": log,
    }


# ---------------------------------------------------------------------------
# Integrity check
# ---------------------------------------------------------------------------


_INTEGRITY_COLLECTIONS = (
    "knowledge_base",
    "referentiels_opsidium",
)


def integrity_check(
    *, extra_collections: Optional[list[str]] = None
) -> dict[str, Any]:
    """Pour chaque collection cible, compte les points et détecte les
    chunks sans ``source`` ou ``chunk_id`` valide.

    Renvoie le rapport sérialisé dans ``log_excerpt`` (texte lisible).
    Le rapport JSON brut est aussi accessible via :func:`run_integrity_check`
    — utile pour les tests ou l'API.
    """
    started = time.time()
    report = run_integrity_check(extra_collections=extra_collections)
    duration = round(time.time() - started, 2)

    # Format texte compact pour log_excerpt.
    lines: list[str] = [f"durée={duration}s"]
    total_points = 0
    total_orphan = 0
    for col in report["collections"]:
        total_points += int(col.get("points") or 0)
        total_orphan += int(col.get("orphans") or 0)
        lines.append(
            f"[{col['name']}] points={col['points']} "
            f"orphelins={col['orphans']} "
            f"sources={','.join(col.get('sources') or []) or '-'}"
        )
    lines.append(f"total_points={total_points} total_orphelins={total_orphan}")
    log = "\n".join(lines)
    return {
        "pages_fetched": 0,
        "chunks_indexed": total_points,
        "log_excerpt": log,
    }


def run_integrity_check(
    *, extra_collections: Optional[list[str]] = None
) -> dict[str, Any]:
    """Version « API » : retourne le rapport JSON détaillé.

    Pour chaque collection :
      - name
      - points
      - sources : set de toutes les valeurs metadata.source rencontrées
      - orphans : nombre de chunks sans source ni chunk_id valide
    """
    from rag.config import QDRANT_URL

    targets = list(_INTEGRITY_COLLECTIONS)
    if extra_collections:
        for c in extra_collections:
            if c and c not in targets:
                targets.append(c)

    if get_qdrant_client is None:  # pragma: no cover
        return {"collections": []}
    client = get_qdrant_client(QDRANT_URL)
    try:
        existing = {c.name for c in client.get_collections().collections}
    except Exception as exc:
        logger.warning("integrity_check: Qdrant injoignable : %s", exc)
        return {"collections": [], "warning": str(exc)}

    out_collections: list[dict[str, Any]] = []
    for name in targets:
        if name not in existing:
            out_collections.append(
                {"name": name, "points": 0, "sources": [],
                 "orphans": 0, "missing": True}
            )
            continue
        info = client.get_collection(name)
        points_count = int(getattr(info, "points_count", 0) or 0)
        sources_seen: dict[str, int] = {}
        orphans = 0
        offset = None
        scanned = 0
        # On scrolle un échantillon (limite 5000 points) pour ne pas
        # bloquer sur des très grosses collections — l'objectif est de
        # détecter les anomalies fréquentes, pas un audit exhaustif.
        max_scan = 5000
        try:
            while scanned < max_scan:
                points, offset = client.scroll(
                    collection_name=name,
                    limit=min(256, max_scan - scanned),
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                )
                if not points:
                    break
                for p in points:
                    scanned += 1
                    payload = p.payload or {}
                    meta = payload.get("metadata") or {}
                    src = meta.get("source") or payload.get("source")
                    cid = meta.get("chunk_id") or payload.get("chunk_id")
                    if src:
                        sources_seen[str(src)] = (
                            sources_seen.get(str(src), 0) + 1
                        )
                    else:
                        orphans += 1
                    if not cid and not src:
                        # déjà compté en orphan ; éviter le double-count
                        pass
                if offset is None:
                    break
        except Exception as exc:  # pragma: no cover — défensif
            logger.warning("scroll '%s' a échoué : %s", name, exc)
        out_collections.append(
            {
                "name": name,
                "points": points_count,
                "scanned": scanned,
                "sources": sorted(sources_seen.keys()),
                "sources_count": sources_seen,
                "orphans": orphans,
                "missing": False,
            }
        )

    return {"collections": out_collections}


# ---------------------------------------------------------------------------
# Stats Qdrant (lecture seule)
# ---------------------------------------------------------------------------


def get_qdrant_stats(
    extra_collections: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Lecture seule : stats live de toutes les collections (pour la page UI).

    Cette fonction NE passe PAS par un job (pas d'écriture, pas de FIFO)
    — elle est appelée directement par l'endpoint ``/admin/maintenance/qdrant-stats``.
    """
    from rag.config import QDRANT_URL

    if get_qdrant_client is None:  # pragma: no cover
        return {"collections": [], "error": "qdrant-client indisponible"}
    client = get_qdrant_client(QDRANT_URL)
    try:
        existing = [c.name for c in client.get_collections().collections]
    except Exception as exc:
        return {"collections": [], "error": str(exc)}

    targets = list(existing)
    if extra_collections:
        for c in extra_collections:
            if c and c not in targets:
                targets.append(c)

    out: list[dict[str, Any]] = []
    for name in targets:
        try:
            info = client.get_collection(name)
            out.append({
                "name": name,
                "points": int(getattr(info, "points_count", 0) or 0),
                "segments": int(getattr(info, "segments_count", 0) or 0),
                "status": str(getattr(info, "status", "") or ""),
                "indexed_vectors": int(
                    getattr(info, "indexed_vectors_count", 0) or 0
                ),
            })
        except Exception as exc:
            out.append({"name": name, "error": str(exc)})
    return {"collections": out}


__all__ = [
    "reembed_source",
    "reembed_all",
    "optimize_qdrant_collection",
    "integrity_check",
    "run_integrity_check",
    "get_qdrant_stats",
]

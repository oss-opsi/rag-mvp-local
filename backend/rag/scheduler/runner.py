"""Runner d'un job de refresh / maintenance.

Verrou FIFO global : un seul job en exécution à la fois (un seul worker thread).
Si un job est déjà ``running`` quand un nouveau est demandé, il reste ``queued``
et sera dépilé à la fin du job courant.

Pause chat optionnelle : si la planification a ``pause_chat_during_refresh=True``,
le runner positionne ``app_settings.chat_paused=1`` au début du job et le retire
à la fin (success ou error).

Notifications : à la fin (success ou error), une entrée est insérée dans
``app_notifications`` pour l'utilisateur ``daniel`` (admin par défaut).
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Any, Callable, Optional

from . import db
from . import maintenance

logger = logging.getLogger(__name__)


# Verrou process : un seul worker à la fois. APScheduler peut nous appeler
# en parallèle (par exemple deux planifications qui se chevauchent), mais
# on souhaite un FIFO strict.
_worker_lock = threading.Lock()
_admin_user = "daniel"


def submit_job(
    *,
    source: str,
    trigger: str,
    schedule_id: Optional[int] = None,
    pause_chat: bool = False,
    optimize_target: Optional[str] = None,
) -> dict[str, Any]:
    """Insère un job ``queued`` puis tente immédiatement de le démarrer.

    Si un autre job tourne déjà, le nouveau reste en file et sera dépilé
    en fin de job courant via ``_drain_queue``.

    ``optimize_target`` : pour les jobs ``optimize_qdrant``, nom de la
    collection à optimiser (stocké dans ``log_excerpt`` jusqu'à exécution).
    """
    job = db.insert_job(
        source=source,
        trigger=trigger,
        schedule_id=schedule_id,
        status="queued",
    )
    if optimize_target:
        db.update_job(job["id"], log_excerpt=f"target={optimize_target}")
    if pause_chat:
        # On mémorise sur le job le toggle pause-chat à utiliser au moment
        # du démarrage. log_excerpt est déjà utilisé pour optimize_target,
        # on encode donc la valeur dans error_message (champ libre tant que
        # le job n'a pas terminé). Évite d'ajouter une colonne pour un seul
        # cas.
        existing = db.get_job(job["id"]) or {}
        prev_log = existing.get("log_excerpt") or ""
        suffix = "pause_chat=1"
        new_log = f"{prev_log}\n{suffix}".strip() if prev_log else suffix
        db.update_job(job["id"], log_excerpt=new_log)
    _try_start_next()
    # Renvoyer la dernière version
    return db.get_job(job["id"]) or job


def _try_start_next() -> None:
    """Démarre le prochain job en file si aucun n'est actif."""
    if db.get_running_job() is not None:
        return
    queued = db.get_next_queued_job()
    if queued is None:
        return
    # Lance dans un thread daemon : le HTTP handler appelant n'est pas
    # bloqué par l'exécution potentiellement très longue.
    t = threading.Thread(
        target=_run_job_safely, args=(queued["id"],), daemon=True,
    )
    t.start()


def _drain_queue() -> None:
    """Appelée à la fin d'un job pour démarrer le suivant en file."""
    _try_start_next()


def _parse_log_for_pause_chat(log_excerpt: Optional[str]) -> bool:
    if not log_excerpt:
        return False
    return "pause_chat=1" in log_excerpt


def _parse_log_for_target(log_excerpt: Optional[str]) -> Optional[str]:
    if not log_excerpt:
        return None
    for line in log_excerpt.splitlines():
        line = line.strip()
        if line.startswith("target="):
            return line.split("=", 1)[1].strip() or None
    return None


def _run_job_safely(job_id: int) -> None:
    """Wrapper qui assure que le verrou est posé/relâché et que le drain
    de la file s'exécute même en cas d'exception."""
    if not _worker_lock.acquire(blocking=False):
        # Un autre worker a démarré entre-temps : on laisse tomber, le
        # drain qu'il déclenchera reprendra ce job.
        return
    try:
        _execute_job(job_id)
    except Exception:  # pragma: no cover — garde-fou ultime
        logger.exception("Crash inattendu dans le worker (job %d)", job_id)
    finally:
        _worker_lock.release()
        _drain_queue()


def _execute_job(job_id: int) -> None:
    job = db.get_job(job_id)
    if job is None:
        logger.warning("Job %d introuvable au démarrage", job_id)
        return
    if job["status"] != "queued":
        # Déjà traité (cancel manuel, race condition).
        return

    pause_chat = _parse_log_for_pause_chat(job.get("log_excerpt"))
    optimize_target = _parse_log_for_target(job.get("log_excerpt"))

    started_at = db._now_iso()
    db.update_job(
        job_id,
        status="running",
        started_at=started_at,
        log_excerpt=None,  # reset (les méta encodées ne servent plus)
    )

    if pause_chat:
        db.set_chat_paused(True)

    started_perf = time.time()
    error_message: Optional[str] = None
    pages_fetched: Optional[int] = None
    chunks_indexed: Optional[int] = None
    success = False
    log_excerpt: Optional[str] = None

    try:
        result = _dispatch_with_override(job["source"], job_id, optimize_target)
        pages_fetched = result.get("pages_fetched")
        chunks_indexed = result.get("chunks_indexed")
        log_excerpt = result.get("log_excerpt")
        success = True
    except Exception as exc:
        logger.exception("Job %d (source=%s) a échoué", job_id, job["source"])
        error_message = str(exc)[:1000]
        log_excerpt = _format_traceback(exc)

    duration = round(time.time() - started_perf, 2)
    finished_at = db._now_iso()

    # Si l'utilisateur a annulé un job ``running``, on respecte cet état.
    final_job = db.get_job(job_id) or {}
    if final_job.get("stop_requested") and not success:
        final_status = "cancelled"
        if error_message is None:
            error_message = "Annulation demandée par l'utilisateur."
    else:
        final_status = "success" if success else "error"

    db.update_job(
        job_id,
        status=final_status,
        finished_at=finished_at,
        duration_s=duration,
        pages_fetched=pages_fetched,
        chunks_indexed=chunks_indexed,
        error_message=error_message,
        log_excerpt=log_excerpt,
    )

    if pause_chat:
        db.set_chat_paused(False)

    # Met à jour last_run_at sur la planification (informatif).
    if job.get("schedule_id"):
        db.set_schedule_runtime(
            int(job["schedule_id"]), last_run_at=finished_at
        )

    _emit_notification(
        source=job["source"],
        status=final_status,
        duration_s=duration,
        pages_fetched=pages_fetched,
        chunks_indexed=chunks_indexed,
        error_message=error_message,
    )


def _format_traceback(exc: Exception) -> str:
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    text = "".join(tb)
    lines = text.strip().splitlines()
    return "\n".join(lines[-200:])


def _emit_notification(
    *,
    source: str,
    status: str,
    duration_s: float,
    pages_fetched: Optional[int],
    chunks_indexed: Optional[int],
    error_message: Optional[str],
) -> None:
    if status == "success":
        title = f"Refresh {source} terminé"
        body = (
            f"{source} : {pages_fetched or 0} pages, "
            f"{chunks_indexed or 0} chunks, {duration_s}s."
        )
        level = "info"
    elif status == "cancelled":
        title = f"Refresh {source} annulé"
        body = error_message or "Annulé par l'utilisateur."
        level = "warn"
    else:
        title = f"Refresh {source} en erreur"
        body = error_message or "Erreur inconnue."
        level = "error"
    try:
        db.insert_notification(
            user=_admin_user, level=level, title=title, body=body,
        )
    except Exception:  # pragma: no cover
        logger.exception("Insertion notification échouée pour le job source=%s", source)


# ---------------------------------------------------------------------------
# Dispatcher : choisit le bon connecteur ou la bonne fonction maintenance
# ---------------------------------------------------------------------------


def _dispatch(
    source: str,
    job_id: int,
    optimize_target: Optional[str],
) -> dict[str, Any]:
    """Exécute la logique correspondant à ``source``.

    Retourne un dict {pages_fetched, chunks_indexed, log_excerpt}.
    """
    if source in db.PUBLIC_SOURCES:
        return _run_public_connector(source, job_id)
    if source.startswith("reembed_"):
        target = source.removeprefix("reembed_")
        if target == "all":
            return maintenance.reembed_all(job_id=job_id)
        return maintenance.reembed_source(target, job_id=job_id)
    if source == "optimize_qdrant":
        if not optimize_target:
            raise ValueError(
                "optimize_qdrant : la cible (collection) est requise."
            )
        return maintenance.optimize_qdrant_collection(optimize_target)
    if source == "integrity_check":
        return maintenance.integrity_check()
    raise ValueError(f"Source inconnue pour dispatch : '{source}'.")


def _run_public_connector(source: str, job_id: int) -> dict[str, Any]:
    """Lance le connecteur public ``source`` en réutilisant le pipeline
    existant côté ``rag.connectors`` + upsert KB.

    Garde la compatibilité avec les fonctions legacy ``_purge_source_from_kb``
    et ``_get_connector`` exposées par ``backend.main`` (Lot 2bis), via une
    indirection propre : le runner ne dépend pas de FastAPI ni de main.
    """
    from rag.connectors.kb_upsert import upsert_chunks_to_kb

    connector = _make_connector(source)
    if connector is None:
        raise ValueError(f"Aucun connecteur pour la source '{source}'.")

    # 1. Purge : supprime les anciens chunks de cette source dans la KB
    pre_purge_msg = ""
    try:
        purged = _purge_source(source)
        pre_purge_msg = f"purgés={purged}\n"
    except Exception as exc:
        # On n'échoue pas le job pour une purge incomplète : on continue.
        pre_purge_msg = f"purge_warning={exc}\n"

    # 2. Fetch + parse + chunk via le connecteur
    pages = 0
    chunks: list = []
    for raw in connector.fetch():
        if db.is_stop_requested(job_id):
            raise RuntimeError("Annulation demandée par l'utilisateur.")
        pages += 1
        try:
            doc = connector.parse(raw)
            chunks.extend(connector.chunk(doc))
        except Exception as exc:
            logger.warning(
                "[%s] parse/chunk a échoué pour %s : %s",
                source, raw.get("url_canonique", "?"), exc,
            )

    # 3. Upsert dans la KB partagée
    upserted = upsert_chunks_to_kb(chunks) if chunks else 0

    log = pre_purge_msg + f"pages={pages}\nchunks={len(chunks)}\nupserted={upserted}"
    return {
        "pages_fetched": pages,
        "chunks_indexed": int(upserted),
        "log_excerpt": log,
    }


def _make_connector(source: str):
    """Factory locale (mêmes connecteurs que ``main._get_connector``)."""
    if source == "service_public":
        from rag.connectors.service_public import ServicePublicConnector
        return ServicePublicConnector()
    if source == "boss":
        from rag.connectors.boss import BossConnector
        return BossConnector()
    if source == "dsn_info":
        from rag.connectors.dsn_info import DsnInfoConnector
        return DsnInfoConnector()
    if source == "urssaf":
        from rag.connectors.urssaf import UrssafConnector
        return UrssafConnector()
    return None


def _purge_source(source: str) -> int:
    """Purge la collection KB partagée pour une source donnée.

    Réutilise le code existant côté Qdrant : on filtre sur metadata.source.
    """
    from qdrant_client.http import models as qmodels
    from rag.config import KNOWLEDGE_BASE_COLLECTION, QDRANT_URL
    from rag.ingest import get_qdrant_client

    client = get_qdrant_client(QDRANT_URL)
    existing = {c.name for c in client.get_collections().collections}
    if KNOWLEDGE_BASE_COLLECTION not in existing:
        return 0
    before = int(
        getattr(client.get_collection(KNOWLEDGE_BASE_COLLECTION), "points_count", 0) or 0
    )
    flt = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="metadata.source",
                match=qmodels.MatchValue(value=source),
            )
        ]
    )
    client.delete(
        collection_name=KNOWLEDGE_BASE_COLLECTION,
        points_selector=qmodels.FilterSelector(filter=flt),
        wait=True,
    )
    after = int(
        getattr(client.get_collection(KNOWLEDGE_BASE_COLLECTION), "points_count", 0) or 0
    )
    return max(0, before - after)


# ---------------------------------------------------------------------------
# Hook test : permet de mocker _run_public_connector et maintenance dans les
# tests sans avoir à patcher d'imports complexes.
# ---------------------------------------------------------------------------


def set_dispatch_override(
    fn: Optional[Callable[[str, int, Optional[str]], dict[str, Any]]],
) -> None:
    """Override le dispatcher (tests uniquement)."""
    global _dispatch_override
    _dispatch_override = fn


_dispatch_override: Optional[
    Callable[[str, int, Optional[str]], dict[str, Any]]
] = None


def _dispatch_with_override(
    source: str, job_id: int, optimize_target: Optional[str]
) -> dict[str, Any]:
    if _dispatch_override is not None:
        return _dispatch_override(source, job_id, optimize_target)
    return _dispatch(source, job_id, optimize_target)



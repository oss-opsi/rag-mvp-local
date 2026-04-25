"""
Gap-analysis jobs module (v4.2.0) — exécution asynchrone de l'analyse d'écarts.

Permet de lancer `run_gap_analysis` en arrière-plan (thread worker) sans bloquer
l'event loop FastAPI ni dépasser le timeout HTTP. Les jobs sont persistés dans
SQLite, un seul job tourne à la fois (verrou), les autres restent en queue.

Statuts :
  - queued  : en attente d'un worker libre
  - running : en cours d'analyse
  - done    : terminé avec succès (analysis_id renseigné, report dans `report_json`)
  - error   : échec (error renseigné)

Schéma :
  gap_analysis_jobs(id, user_id, cdc_id, status, force_refresh, openai_api_key,
                    analysis_id, report_json, error,
                    created_at, started_at, finished_at)

NB : la clé OpenAI est stockée le temps du job (lifecycle court). Elle est
remise à NULL une fois le job terminé pour limiter l'exposition.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from rag.config import DATA_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

JOBS_DB_PATH = os.path.join(DATA_DIR, "gap_analysis_jobs.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gap_analysis_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT    NOT NULL,
    cdc_id          INTEGER NOT NULL,
    status          TEXT    NOT NULL,
    force_refresh   INTEGER NOT NULL DEFAULT 0,
    openai_api_key  TEXT,
    analysis_id     INTEGER,
    report_json     TEXT,
    error           TEXT,
    created_at      TEXT    NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_gajobs_user_created
    ON gap_analysis_jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gajobs_status
    ON gap_analysis_jobs(status);
CREATE INDEX IF NOT EXISTS idx_gajobs_user_cdc
    ON gap_analysis_jobs(user_id, cdc_id, created_at DESC);
"""

# Champs jamais renvoyés au client (clé API).
_SENSITIVE_FIELDS = ("openai_api_key",)

# ---------------------------------------------------------------------------
# Globals (single-process worker)
# ---------------------------------------------------------------------------

_claim_lock = threading.Lock()
_worker_started = False
_worker_started_lock = threading.Lock()

# Injecté à l'init (évite l'import circulaire avec main.py).
# Signature attendue : async (cdc_id, user_id, openai_api_key, force_refresh)
#                              -> {"analysis_id": int|None, "report": dict}
_run_callable: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(JOBS_DB_PATH, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    """Créer la table gap_analysis_jobs. Sûr à chaque démarrage."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # Recovery : tout job laissé "running" suite à un crash est marqué error.
        conn.execute(
            """
            UPDATE gap_analysis_jobs
               SET status = 'error',
                   error = COALESCE(error, 'Interrompu par redémarrage du service'),
                   finished_at = ?,
                   openai_api_key = NULL
             WHERE status = 'running'
            """,
            (_now_iso(),),
        )
    logger.info("Gap analysis jobs DB initialised at %s", JOBS_DB_PATH)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _row_to_public(row: dict[str, Any]) -> dict[str, Any]:
    """Strippe la clé API et désérialise report_json pour l'API."""
    out = dict(row)
    for k in _SENSITIVE_FIELDS:
        out.pop(k, None)
    if out.get("force_refresh") is not None:
        out["force_refresh"] = bool(out["force_refresh"])
    raw = out.pop("report_json", None)
    if raw:
        try:
            out["report"] = json.loads(raw)
        except (TypeError, ValueError):
            out["report"] = None
    else:
        out["report"] = None
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure(
    run_callable: Callable[..., Awaitable[dict[str, Any]]],
) -> None:
    """Injecte la callable d'exécution (évite l'import circulaire)."""
    global _run_callable
    _run_callable = run_callable


def enqueue_job(
    user_id: str,
    cdc_id: int,
    openai_api_key: str,
    force_refresh: bool,
) -> dict[str, Any]:
    """Insère un job 'queued' et réveille le worker. Retourne la ligne (publique)."""
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO gap_analysis_jobs(
                user_id, cdc_id, status, force_refresh, openai_api_key, created_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                user_id,
                int(cdc_id),
                "queued",
                1 if force_refresh else 0,
                openai_api_key,
                _now_iso(),
            ),
        )
        job_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM gap_analysis_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    _ensure_worker_running()
    return _row_to_public(dict(row))


def get_job(user_id: str, job_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM gap_analysis_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
        return _row_to_public(dict(row)) if row else None


def list_jobs(
    user_id: str,
    status: Optional[str] = None,
    cdc_id: Optional[int] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Liste les jobs d'un user (récents d'abord). status accepte CSV."""
    sql = "SELECT * FROM gap_analysis_jobs WHERE user_id = ?"
    params: list[Any] = [user_id]
    if cdc_id is not None:
        sql += " AND cdc_id = ?"
        params.append(int(cdc_id))
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            sql += f" AND status IN ({placeholders})"
            params.extend(statuses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_public(dict(r)) for r in rows]


def find_active_job_for_cdc(user_id: str, cdc_id: int) -> Optional[dict[str, Any]]:
    """Retourne le job queued/running existant pour ce CDC, s'il y en a un."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM gap_analysis_jobs
             WHERE user_id = ? AND cdc_id = ?
               AND status IN ('queued','running')
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (user_id, int(cdc_id)),
        ).fetchone()
        return _row_to_public(dict(row)) if row else None


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------


def _claim_next_job() -> Optional[dict[str, Any]]:
    """Atomically pick the oldest queued job and mark it running."""
    with _claim_lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM gap_analysis_jobs
             WHERE status = 'queued'
             ORDER BY created_at ASC
             LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE gap_analysis_jobs SET status='running', started_at=? WHERE id=?",
            (_now_iso(), row["id"]),
        )
        updated = conn.execute(
            "SELECT * FROM gap_analysis_jobs WHERE id=?", (row["id"],)
        ).fetchone()
        return dict(updated)  # NB : interne, on garde la clé API ici


def _finish_job(
    job_id: int,
    *,
    success: bool,
    analysis_id: Optional[int],
    report: Optional[dict[str, Any]],
    error: Optional[str],
) -> None:
    payload = json.dumps(report, ensure_ascii=False) if report is not None else None
    with _connect() as conn:
        conn.execute(
            """
            UPDATE gap_analysis_jobs
               SET status = ?,
                   analysis_id = ?,
                   report_json = ?,
                   error = ?,
                   finished_at = ?,
                   openai_api_key = NULL
             WHERE id = ?
            """,
            (
                "done" if success else "error",
                analysis_id,
                payload,
                error,
                _now_iso(),
                job_id,
            ),
        )


def _process_job(job: dict[str, Any]) -> None:
    """Run run_gap_analysis pour un job claim et persiste le résultat."""
    assert _run_callable is not None, (
        "gap_analysis_jobs.configure() must be called at startup"
    )
    job_id = int(job["id"])
    user_id = job["user_id"]
    cdc_id = int(job["cdc_id"])
    api_key = job.get("openai_api_key") or ""
    force_refresh = bool(job.get("force_refresh"))

    logger.info(
        "Gap analysis worker: job %d starting — user=%s cdc=%d",
        job_id,
        user_id,
        cdc_id,
    )
    try:
        # Le callable est async (run_gap_analysis l'est) → on le run dans
        # une boucle dédiée à ce thread.
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                _run_callable(
                    cdc_id=cdc_id,
                    user_id=user_id,
                    openai_api_key=api_key,
                    force_refresh=force_refresh,
                )
            )
        finally:
            try:
                loop.close()
            except Exception:  # pragma: no cover
                pass
        analysis_id = result.get("analysis_id") if result else None
        report = result.get("report") if result else None
        _finish_job(
            job_id,
            success=True,
            analysis_id=int(analysis_id) if analysis_id is not None else None,
            report=report,
            error=None,
        )
        logger.info(
            "Gap analysis worker: job %d done (analysis_id=%s)",
            job_id,
            analysis_id,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Gap analysis worker: job %d failed", job_id)
        _finish_job(
            job_id,
            success=False,
            analysis_id=None,
            report=None,
            error=str(exc)[:500],
        )


def _worker_loop() -> None:
    """Boucle de fond : pull les jobs queued un par un."""
    logger.info("Gap analysis worker loop started")
    idle_sleep = 2.0
    while True:
        try:
            job = _claim_next_job()
        except Exception:  # pragma: no cover
            logger.exception("Gap analysis worker: claim failed")
            time.sleep(idle_sleep)
            continue
        if job is None:
            time.sleep(idle_sleep)
            continue
        _process_job(job)


def _ensure_worker_running() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_started_lock:
        if _worker_started:
            return
        t = threading.Thread(
            target=_worker_loop, name="gap-analysis-worker", daemon=True
        )
        t.start()
        _worker_started = True
        logger.info("Gap analysis worker thread started")


def start_worker_on_boot() -> None:
    """Entrypoint explicite (FastAPI on_event='startup')."""
    _ensure_worker_running()

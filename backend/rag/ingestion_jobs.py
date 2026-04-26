"""
Ingestion jobs module (v4.1.0) — ingestion asynchrone des documents.

Permet de lancer `ingest_file` en arrière-plan (thread worker) sans bloquer
l'event loop FastAPI. Les jobs sont persistés dans SQLite, un seul job tourne
à la fois (verrou), les autres restent en queue.

Statuts :
  - queued  : en attente d'un worker libre
  - running : en cours d'ingestion
  - done    : terminé avec succès (chunk_count renseigné)
  - error   : échec (error renseigné)

Schéma :
  ingestion_jobs(id, user_id, filename, tmp_path, status, chunk_count,
                 error, created_at, started_at, finished_at)
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from rag.config import DATA_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

JOBS_DB_PATH = os.path.join(DATA_DIR, "ingestion_jobs.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT    NOT NULL,
    filename     TEXT    NOT NULL,
    tmp_path     TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    chunk_count  INTEGER,
    error        TEXT,
    created_at   TEXT    NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_created
    ON ingestion_jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON ingestion_jobs(status);
"""

# ---------------------------------------------------------------------------
# Globals (single-process worker)
# ---------------------------------------------------------------------------

# Serialize queue polling / claim. The actual ingest_file work happens
# outside this lock (it's CPU-heavy) — but only one worker thread is
# running at any time by design (see _worker_thread).
_claim_lock = threading.Lock()
_worker_started = False
_worker_started_lock = threading.Lock()

# Injected at init (avoids a top-level circular import with main.py).
_ingest_callable: Optional[Callable[..., int]] = None
_qdrant_url: Optional[str] = None


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
    """Create the ingestion_jobs table. Safe on every startup."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # Recovery: any job left "running" from a previous crash is flipped
        # to error so it doesn't stay stuck.
        conn.execute(
            """
            UPDATE ingestion_jobs
               SET status = 'error',
                   error = COALESCE(error, 'Interrompu par redémarrage du service'),
                   finished_at = ?
             WHERE status = 'running'
            """,
            (_now_iso(),),
        )
    logger.info("Ingestion jobs DB initialised at %s", JOBS_DB_PATH)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure(
    ingest_callable: Callable[..., int],
    qdrant_url: str,
) -> None:
    """Inject the ingest function and qdrant URL to avoid circular imports."""
    global _ingest_callable, _qdrant_url
    _ingest_callable = ingest_callable
    _qdrant_url = qdrant_url


def enqueue_job(user_id: str, filename: str, tmp_path: str) -> dict[str, Any]:
    """Insert a new job in 'queued' status and wake the worker. Returns the row."""
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO ingestion_jobs(
                user_id, filename, tmp_path, status, created_at
            ) VALUES (?,?,?,'queued',?)
            """,
            (user_id, filename, tmp_path, _now_iso()),
        )
        job_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    _ensure_worker_running()
    return dict(row)


def get_job(user_id: str, job_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM ingestion_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def list_jobs(
    user_id: str,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    List jobs for a user, most recent first.
    `status` can be a single status or comma-separated list (e.g. 'queued,running').
    """
    sql = "SELECT * FROM ingestion_jobs WHERE user_id = ?"
    params: list[Any] = [user_id]
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
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------


def _claim_next_job() -> Optional[dict[str, Any]]:
    """
    Atomically pick the oldest queued job and mark it running.
    Returns the job dict or None if none pending.
    """
    with _claim_lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM ingestion_jobs
             WHERE status = 'queued'
             ORDER BY created_at ASC
             LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE ingestion_jobs SET status='running', started_at=? WHERE id=?",
            (_now_iso(), row["id"]),
        )
        updated = conn.execute(
            "SELECT * FROM ingestion_jobs WHERE id=?", (row["id"],)
        ).fetchone()
        return dict(updated)


def _finish_job(
    job_id: int, *, success: bool, chunk_count: Optional[int], error: Optional[str]
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE ingestion_jobs
               SET status = ?,
                   chunk_count = ?,
                   error = ?,
                   finished_at = ?
             WHERE id = ?
            """,
            (
                "done" if success else "error",
                chunk_count,
                error,
                _now_iso(),
                job_id,
            ),
        )


def _process_job(job: dict[str, Any]) -> None:
    """Run ingest_file for a claimed job and persist the outcome."""
    assert _ingest_callable is not None and _qdrant_url is not None, (
        "ingestion_jobs.configure() must be called at startup"
    )
    job_id = int(job["id"])
    tmp_path = job["tmp_path"]
    filename = job["filename"]
    user_id = job["user_id"]

    logger.info(
        "Ingestion worker: job %d starting — user=%s file=%s",
        job_id,
        user_id,
        filename,
    )
    try:
        chunk_count = _ingest_callable(
            file_path=tmp_path,
            source_name=filename,
            user_id=user_id,
            qdrant_url=_qdrant_url,
        )
        _finish_job(
            job_id, success=True, chunk_count=int(chunk_count), error=None
        )
        logger.info(
            "Ingestion worker: job %d done (%d chunks)", job_id, chunk_count
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Ingestion worker: job %d failed", job_id)
        _finish_job(
            job_id, success=False, chunk_count=None, error=str(exc)[:500]
        )
    finally:
        # Best-effort cleanup of the temp file
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            logger.warning(
                "Could not remove temp file %s for job %d", tmp_path, job_id
            )


def _worker_loop() -> None:
    """Background loop: pull queued jobs and process them one at a time."""
    logger.info("Ingestion worker loop started")
    idle_sleep = 2.0
    while True:
        try:
            job = _claim_next_job()
        except Exception:  # pragma: no cover
            logger.exception("Ingestion worker: claim failed")
            time.sleep(idle_sleep)
            continue
        if job is None:
            time.sleep(idle_sleep)
            continue
        _process_job(job)


def _ensure_worker_running() -> None:
    """Start the worker thread on first enqueue (idempotent)."""
    global _worker_started
    if _worker_started:
        return
    with _worker_started_lock:
        if _worker_started:
            return
        t = threading.Thread(
            target=_worker_loop, name="ingestion-worker", daemon=True
        )
        t.start()
        _worker_started = True
        logger.info("Ingestion worker thread started")


def start_worker_on_boot() -> None:
    """Explicit startup entrypoint (FastAPI on_event='startup')."""
    _ensure_worker_running()

"""Schéma SQLite et helpers CRUD pour la Page Admin Planificateur.

Tables :
  - scheduled_refreshes : planifications cron des connecteurs sources publiques
  - refresh_jobs        : historique des exécutions (manuel + planifié)
  - app_notifications   : notifications internes (succès/erreur job)
  - app_settings        : table partagée — clé `chat_paused` posée par le runner
                          quand pause_chat_during_refresh=True.

Le module ne sait rien d'APScheduler : c'est ``manager.py`` qui orchestre.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from rag.config import DATA_DIR

logger = logging.getLogger(__name__)

SCHEDULER_DB_PATH = os.path.join(DATA_DIR, "scheduler.db")

# Whitelist des sources autorisées (refusées au niveau API si autre).
# - 4 connecteurs publics
# - reembed_<source> : re-embedding complet d'une source publique
# - reembed_all      : enchaîne le re-embedding des 4 sources publiques
# - optimize_qdrant  : optimize d'une collection Qdrant (cible passée en log_excerpt)
# - integrity_check  : vérification d'intégrité multi-collections
PUBLIC_SOURCES: tuple[str, ...] = ("boss", "urssaf", "dsn_info", "service_public")
MAINTENANCE_SOURCES: tuple[str, ...] = (
    "reembed_boss",
    "reembed_urssaf",
    "reembed_dsn_info",
    "reembed_service_public",
    "reembed_all",
    "optimize_qdrant",
    "integrity_check",
)
VALID_SOURCES: tuple[str, ...] = PUBLIC_SOURCES + MAINTENANCE_SOURCES
VALID_TRIGGERS: tuple[str, ...] = ("cron", "manual")
VALID_STATUSES: tuple[str, ...] = (
    "queued", "running", "success", "error", "cancelled",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_refreshes (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    source                      TEXT    NOT NULL,
    cron_expression             TEXT    NOT NULL,
    enabled                     INTEGER NOT NULL DEFAULT 1,
    pause_chat_during_refresh   INTEGER NOT NULL DEFAULT 0,
    label                       TEXT,
    last_run_at                 TEXT,
    next_run_at                 TEXT,
    created_at                  TEXT    NOT NULL,
    created_by                  TEXT
);

CREATE INDEX IF NOT EXISTS idx_sched_source ON scheduled_refreshes(source);
CREATE INDEX IF NOT EXISTS idx_sched_enabled ON scheduled_refreshes(enabled);

CREATE TABLE IF NOT EXISTS refresh_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id     INTEGER,
    source          TEXT    NOT NULL,
    trigger         TEXT    NOT NULL CHECK(trigger IN ('cron','manual')),
    status          TEXT    NOT NULL
        CHECK(status IN ('queued','running','success','error','cancelled')),
    started_at      TEXT,
    finished_at     TEXT,
    duration_s      REAL,
    pages_fetched   INTEGER,
    chunks_indexed  INTEGER,
    error_message   TEXT,
    log_excerpt     TEXT,
    stop_requested  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (schedule_id) REFERENCES scheduled_refreshes(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_started_desc
    ON refresh_jobs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON refresh_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON refresh_jobs(source);

CREATE TABLE IF NOT EXISTS app_notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user        TEXT    NOT NULL,
    level       TEXT    NOT NULL CHECK(level IN ('info','warn','error')),
    title       TEXT    NOT NULL,
    body        TEXT,
    created_at  TEXT    NOT NULL,
    read_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_notif_user_unread
    ON app_notifications(user, read_at);
CREATE INDEX IF NOT EXISTS idx_notif_created
    ON app_notifications(created_at DESC);

CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SCHEDULER_DB_PATH, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_scheduler_db() -> None:
    """Crée les tables si absentes. Idempotent. À appeler au startup."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # Récupération de jobs orphelins suite à un crash :
        conn.execute(
            """
            UPDATE refresh_jobs
               SET status = 'error',
                   error_message = COALESCE(error_message,
                       'Interrompu par redémarrage du backend.'),
                   finished_at = ?
             WHERE status IN ('running')
            """,
            (_now_iso(),),
        )
        # Si on redémarre alors que chat_paused était à 1, on libère.
        conn.execute(
            """
            UPDATE app_settings
               SET value = '0', updated_at = ?
             WHERE key = 'chat_paused' AND value = '1'
            """,
            (_now_iso(),),
        )
    logger.info("Scheduler DB initialisée à %s", SCHEDULER_DB_PATH)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# scheduled_refreshes — CRUD
# ---------------------------------------------------------------------------


def list_schedules(enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM scheduled_refreshes"
    params: tuple[Any, ...] = ()
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY created_at DESC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_schedule(dict(r)) for r in rows]


def get_schedule(schedule_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM scheduled_refreshes WHERE id = ?", (schedule_id,)
        ).fetchone()
    return _row_to_schedule(dict(row)) if row else None


def create_schedule(
    *,
    source: str,
    cron_expression: str,
    enabled: bool = True,
    pause_chat_during_refresh: bool = False,
    label: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict[str, Any]:
    if source not in VALID_SOURCES:
        raise ValueError(
            f"Source invalide : '{source}'. Attendu : {', '.join(VALID_SOURCES)}."
        )
    cron_expression = (cron_expression or "").strip()
    if not cron_expression:
        raise ValueError("Expression cron manquante.")
    now = _now_iso()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO scheduled_refreshes(
                source, cron_expression, enabled, pause_chat_during_refresh,
                label, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                source,
                cron_expression,
                1 if enabled else 0,
                1 if pause_chat_during_refresh else 0,
                label,
                now,
                created_by,
            ),
        )
        sid = cur.lastrowid
    sched = get_schedule(sid)
    assert sched is not None
    return sched


def update_schedule(
    schedule_id: int,
    *,
    cron_expression: Optional[str] = None,
    enabled: Optional[bool] = None,
    pause_chat_during_refresh: Optional[bool] = None,
    label: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    fields: list[str] = []
    params: list[Any] = []
    if cron_expression is not None:
        fields.append("cron_expression = ?")
        params.append(cron_expression)
    if enabled is not None:
        fields.append("enabled = ?")
        params.append(1 if enabled else 0)
    if pause_chat_during_refresh is not None:
        fields.append("pause_chat_during_refresh = ?")
        params.append(1 if pause_chat_during_refresh else 0)
    if label is not None:
        fields.append("label = ?")
        params.append(label)
    if not fields:
        return get_schedule(schedule_id)
    params.append(schedule_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE scheduled_refreshes SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
    return get_schedule(schedule_id)


def delete_schedule(schedule_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM scheduled_refreshes WHERE id = ?", (schedule_id,)
        )
        return cur.rowcount > 0


def set_schedule_runtime(
    schedule_id: int,
    *,
    last_run_at: Optional[str] = None,
    next_run_at: Optional[str] = None,
) -> None:
    """Met à jour les colonnes purement informatives last_run_at / next_run_at."""
    fields: list[str] = []
    params: list[Any] = []
    if last_run_at is not None:
        fields.append("last_run_at = ?")
        params.append(last_run_at)
    if next_run_at is not None:
        fields.append("next_run_at = ?")
        params.append(next_run_at)
    if not fields:
        return
    params.append(schedule_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE scheduled_refreshes SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )


def _row_to_schedule(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["enabled"] = bool(row.get("enabled"))
    out["pause_chat_during_refresh"] = bool(
        row.get("pause_chat_during_refresh")
    )
    return out


# ---------------------------------------------------------------------------
# refresh_jobs — CRUD
# ---------------------------------------------------------------------------


def insert_job(
    *,
    source: str,
    trigger: str,
    schedule_id: Optional[int] = None,
    status: str = "queued",
) -> dict[str, Any]:
    if source not in VALID_SOURCES:
        raise ValueError(f"Source invalide : '{source}'.")
    if trigger not in VALID_TRIGGERS:
        raise ValueError(f"Trigger invalide : '{trigger}'.")
    if status not in VALID_STATUSES:
        raise ValueError(f"Status invalide : '{status}'.")
    now = _now_iso()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO refresh_jobs(
                schedule_id, source, trigger, status, created_at
            ) VALUES (?,?,?,?,?)
            """,
            (schedule_id, source, trigger, status, now),
        )
        job_id = cur.lastrowid
    job = get_job(job_id)
    assert job is not None
    return job


def update_job(
    job_id: int,
    *,
    status: Optional[str] = None,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    duration_s: Optional[float] = None,
    pages_fetched: Optional[int] = None,
    chunks_indexed: Optional[int] = None,
    error_message: Optional[str] = None,
    log_excerpt: Optional[str] = None,
    stop_requested: Optional[bool] = None,
) -> Optional[dict[str, Any]]:
    fields: list[str] = []
    params: list[Any] = []
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Status invalide : '{status}'.")
        fields.append("status = ?")
        params.append(status)
    if started_at is not None:
        fields.append("started_at = ?")
        params.append(started_at)
    if finished_at is not None:
        fields.append("finished_at = ?")
        params.append(finished_at)
    if duration_s is not None:
        fields.append("duration_s = ?")
        params.append(float(duration_s))
    if pages_fetched is not None:
        fields.append("pages_fetched = ?")
        params.append(int(pages_fetched))
    if chunks_indexed is not None:
        fields.append("chunks_indexed = ?")
        params.append(int(chunks_indexed))
    if error_message is not None:
        fields.append("error_message = ?")
        params.append(error_message)
    if log_excerpt is not None:
        fields.append("log_excerpt = ?")
        params.append(log_excerpt)
    if stop_requested is not None:
        fields.append("stop_requested = ?")
        params.append(1 if stop_requested else 0)
    if not fields:
        return get_job(job_id)
    params.append(job_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE refresh_jobs SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
    return get_job(job_id)


def get_job(job_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM refresh_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return _row_to_job(dict(row)) if row else None


def list_jobs(
    *,
    source: Optional[str] = None,
    status: Optional[Iterable[str]] = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM refresh_jobs WHERE 1=1"
    params: list[Any] = []
    if source:
        sql += " AND source = ?"
        params.append(source)
    if status:
        statuses = [s for s in status if s]
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            sql += f" AND status IN ({placeholders})"
            params.extend(statuses)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])
    with _connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_job(dict(r)) for r in rows]


def get_running_job() -> Optional[dict[str, Any]]:
    """Retourne le job actuellement en exécution (status='running'), s'il y en a un."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM refresh_jobs WHERE status='running' "
            "ORDER BY id ASC LIMIT 1"
        ).fetchone()
    return _row_to_job(dict(row)) if row else None


def get_next_queued_job() -> Optional[dict[str, Any]]:
    """Plus ancien job en file d'attente (FIFO)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM refresh_jobs WHERE status='queued' "
            "ORDER BY id ASC LIMIT 1"
        ).fetchone()
    return _row_to_job(dict(row)) if row else None


def is_stop_requested(job_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT stop_requested FROM refresh_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    return bool(row["stop_requested"]) if row else False


def _row_to_job(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["stop_requested"] = bool(row.get("stop_requested"))
    return out


# ---------------------------------------------------------------------------
# app_settings — clé/valeur partagée (chat_paused notamment)
# ---------------------------------------------------------------------------


def get_setting(key: str, default: str = "") -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES (?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                            updated_at=excluded.updated_at
            """,
            (key, value, now),
        )


def is_chat_paused() -> bool:
    return get_setting("chat_paused", "0") == "1"


def set_chat_paused(paused: bool) -> None:
    set_setting("chat_paused", "1" if paused else "0")


# ---------------------------------------------------------------------------
# app_notifications
# ---------------------------------------------------------------------------


def insert_notification(
    *,
    user: str,
    level: str,
    title: str,
    body: Optional[str] = None,
) -> dict[str, Any]:
    if level not in {"info", "warn", "error"}:
        raise ValueError(f"Level invalide : '{level}'.")
    now = _now_iso()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO app_notifications(user, level, title, body, created_at)
            VALUES (?,?,?,?,?)
            """,
            (user, level, title, body, now),
        )
        nid = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM app_notifications WHERE id = ?", (nid,)
        ).fetchone()
    return dict(row)


def list_notifications(
    user: str,
    *,
    unread_only: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM app_notifications WHERE user = ?"
    params: list[Any] = [user]
    if unread_only:
        sql += " AND read_at IS NULL"
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with _connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def count_unread_notifications(user: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM app_notifications "
            "WHERE user = ? AND read_at IS NULL",
            (user,),
        ).fetchone()
    return int(row["c"]) if row else 0


def mark_notification_read(notification_id: int, user: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE app_notifications
               SET read_at = ?
             WHERE id = ? AND user = ? AND read_at IS NULL
            """,
            (_now_iso(), notification_id, user),
        )
        return cur.rowcount > 0


def mark_all_notifications_read(user: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE app_notifications
               SET read_at = ?
             WHERE user = ? AND read_at IS NULL
            """,
            (_now_iso(), user),
        )
        return cur.rowcount


def delete_notification(notification_id: int, user: str) -> bool:
    """Supprime définitivement une notification de l'utilisateur courant."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM app_notifications WHERE id = ? AND user = ?",
            (notification_id, user),
        )
        return cur.rowcount > 0


__all__ = [
    "SCHEDULER_DB_PATH",
    "VALID_SOURCES",
    "VALID_TRIGGERS",
    "VALID_STATUSES",
    "init_scheduler_db",
    "list_schedules",
    "get_schedule",
    "create_schedule",
    "update_schedule",
    "delete_schedule",
    "set_schedule_runtime",
    "insert_job",
    "update_job",
    "get_job",
    "list_jobs",
    "get_running_job",
    "get_next_queued_job",
    "is_stop_requested",
    "get_setting",
    "set_setting",
    "is_chat_paused",
    "set_chat_paused",
    "insert_notification",
    "list_notifications",
    "count_unread_notifications",
    "mark_notification_read",
    "mark_all_notifications_read",
]

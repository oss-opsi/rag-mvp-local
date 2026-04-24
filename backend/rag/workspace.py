"""
Workspace module (v3.6.0) — Espace de travail multi-clients pour l'analyse d'écarts.

Stocke les clients, leurs cahiers des charges (CDC) et les rapports d'analyse
dans une base SQLite, avec les fichiers originaux sur disque. Chaque utilisateur
a son propre espace (isolé par user_id).

Schéma :
  clients(id, user_id, name, created_at)
  cdcs(id, client_id, filename, ext, original_path, file_size, sha256, uploaded_at)
  analyses(id, cdc_id, created_at, total, covered, partial, missing, ambiguous,
           coverage_percent, chunks_processed, pipeline_version,
           corpus_fingerprint, report_json)

Statut d'un CDC (dérivé) :
  - "brouillon" : aucune analyse
  - "analysé"   : dernière analyse avec pipeline_version courant ET même corpus
  - "périmé"    : analyse existante mais pipeline_version obsolète OU corpus modifié
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from rag.config import DATA_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

WORKSPACE_DB_PATH = os.path.join(DATA_DIR, "gap_workspace.db")
CDC_STORAGE_ROOT = os.path.join(DATA_DIR, "cdc_storage")

# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    UNIQUE(user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_clients_user ON clients(user_id);

CREATE TABLE IF NOT EXISTS cdcs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id      INTEGER NOT NULL,
    filename       TEXT    NOT NULL,
    ext            TEXT    NOT NULL,
    original_path  TEXT    NOT NULL,
    file_size      INTEGER NOT NULL,
    sha256         TEXT    NOT NULL,
    uploaded_at    TEXT    NOT NULL,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cdcs_client ON cdcs(client_id);

CREATE TABLE IF NOT EXISTS analyses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cdc_id              INTEGER NOT NULL,
    created_at          TEXT    NOT NULL,
    total               INTEGER NOT NULL,
    covered             INTEGER NOT NULL,
    partial             INTEGER NOT NULL,
    missing             INTEGER NOT NULL,
    ambiguous           INTEGER NOT NULL,
    coverage_percent    REAL    NOT NULL,
    chunks_processed    INTEGER NOT NULL,
    pipeline_version    TEXT    NOT NULL,
    corpus_fingerprint  TEXT    NOT NULL,
    report_json         TEXT    NOT NULL,
    FOREIGN KEY (cdc_id) REFERENCES cdcs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analyses_cdc ON analyses(cdc_id);
CREATE INDEX IF NOT EXISTS idx_analyses_cdc_created
    ON analyses(cdc_id, created_at DESC);
"""


def _connect() -> sqlite3.Connection:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(WORKSPACE_DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    """Create tables if they do not exist. Safe to call on every startup."""
    Path(CDC_STORAGE_ROOT).mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    logger.info("Workspace DB initialised at %s", WORKSPACE_DB_PATH)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    # ISO 8601 with timezone Z (UTC)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _user_storage_dir(user_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)
    path = os.path.join(CDC_STORAGE_ROOT, safe)
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# CLIENTS CRUD
# ---------------------------------------------------------------------------


def list_clients(user_id: str) -> list[dict[str, Any]]:
    """Return all clients for a user, with CDC counts."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.name, c.created_at,
                   (SELECT COUNT(*) FROM cdcs WHERE cdcs.client_id = c.id)
                       AS cdc_count
            FROM clients c
            WHERE c.user_id = ?
            ORDER BY c.name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def create_client(user_id: str, name: str) -> dict[str, Any]:
    """Create a new client. Raises ValueError on duplicate or invalid name."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Le nom du client est requis.")
    if len(name) > 120:
        raise ValueError("Le nom du client doit contenir au maximum 120 caractères.")
    created_at = _now_iso()
    with _connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO clients(user_id, name, created_at) VALUES (?,?,?)",
                (user_id, name, created_at),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"Un client nommé « {name} » existe déjà.")
        client_id = cur.lastrowid
    return {"id": client_id, "name": name, "created_at": created_at, "cdc_count": 0}


def get_client(user_id: str, client_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, created_at FROM clients WHERE id=? AND user_id=?",
            (client_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def delete_client(user_id: str, client_id: int) -> bool:
    """Delete a client + cascade its CDCs and analyses. Removes files on disk."""
    with _connect() as conn:
        # Gather original file paths to remove from disk
        rows = conn.execute(
            """
            SELECT cdcs.original_path FROM cdcs
            JOIN clients ON clients.id = cdcs.client_id
            WHERE clients.id = ? AND clients.user_id = ?
            """,
            (client_id, user_id),
        ).fetchall()
        file_paths = [r["original_path"] for r in rows]
        cur = conn.execute(
            "DELETE FROM clients WHERE id=? AND user_id=?",
            (client_id, user_id),
        )
        deleted = cur.rowcount > 0
    # Remove files best-effort
    for p in file_paths:
        try:
            if p and os.path.exists(p):
                os.unlink(p)
        except OSError as exc:
            logger.warning("Failed to delete CDC file %s: %s", p, exc)
    return deleted


# ---------------------------------------------------------------------------
# CDC CRUD
# ---------------------------------------------------------------------------


def list_cdcs(user_id: str, client_id: int) -> list[dict[str, Any]]:
    """Return all CDCs for a client, each with its latest analysis summary."""
    with _connect() as conn:
        # Confirm the client belongs to the user
        owner = conn.execute(
            "SELECT 1 FROM clients WHERE id=? AND user_id=?",
            (client_id, user_id),
        ).fetchone()
        if not owner:
            return []
        rows = conn.execute(
            """
            SELECT cdcs.id, cdcs.filename, cdcs.ext, cdcs.file_size,
                   cdcs.sha256, cdcs.uploaded_at,
                   a.id                 AS analysis_id,
                   a.created_at         AS analysed_at,
                   a.total              AS total,
                   a.covered            AS covered,
                   a.partial            AS partial,
                   a.missing            AS missing,
                   a.ambiguous          AS ambiguous,
                   a.coverage_percent   AS coverage_percent,
                   a.chunks_processed   AS chunks_processed,
                   a.pipeline_version   AS pipeline_version,
                   a.corpus_fingerprint AS corpus_fingerprint
            FROM cdcs
            LEFT JOIN (
                SELECT a1.* FROM analyses a1
                INNER JOIN (
                    SELECT cdc_id, MAX(created_at) AS max_ts
                    FROM analyses GROUP BY cdc_id
                ) mx ON mx.cdc_id = a1.cdc_id AND mx.max_ts = a1.created_at
            ) a ON a.cdc_id = cdcs.id
            WHERE cdcs.client_id = ?
            ORDER BY cdcs.uploaded_at DESC
            """,
            (client_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_cdc(user_id: str, cdc_id: int) -> Optional[dict[str, Any]]:
    """Return a CDC if it belongs to the user (via its client)."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT cdcs.id, cdcs.client_id, cdcs.filename, cdcs.ext,
                   cdcs.original_path, cdcs.file_size, cdcs.sha256,
                   cdcs.uploaded_at,
                   clients.name AS client_name, clients.user_id
            FROM cdcs
            JOIN clients ON clients.id = cdcs.client_id
            WHERE cdcs.id = ? AND clients.user_id = ?
            """,
            (cdc_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def create_cdc(
    user_id: str,
    client_id: int,
    filename: str,
    ext: str,
    data: bytes,
) -> dict[str, Any]:
    """Persist a new CDC (file on disk + DB row). Returns the inserted row."""
    if not filename:
        raise ValueError("Le nom de fichier est requis.")
    owner = get_client(user_id, client_id)
    if not owner:
        raise ValueError("Client introuvable.")
    sha256 = _sha256_bytes(data)
    uploaded_at = _now_iso()
    user_dir = _user_storage_dir(user_id)

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO cdcs(client_id, filename, ext, original_path,
                             file_size, sha256, uploaded_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (client_id, filename, ext, "", len(data), sha256, uploaded_at),
        )
        cdc_id = cur.lastrowid
        # Write file using the CDC id to guarantee uniqueness
        safe_ext = ext if ext.startswith(".") else f".{ext}"
        file_path = os.path.join(user_dir, f"{cdc_id}{safe_ext}")
        with open(file_path, "wb") as f:
            f.write(data)
        conn.execute(
            "UPDATE cdcs SET original_path=? WHERE id=?",
            (file_path, cdc_id),
        )

    return {
        "id": cdc_id,
        "client_id": client_id,
        "filename": filename,
        "ext": ext,
        "original_path": file_path,
        "file_size": len(data),
        "sha256": sha256,
        "uploaded_at": uploaded_at,
    }


def delete_cdc(user_id: str, cdc_id: int) -> bool:
    """Delete a CDC (and cascade its analyses). Removes file on disk."""
    cdc = get_cdc(user_id, cdc_id)
    if not cdc:
        return False
    with _connect() as conn:
        conn.execute("DELETE FROM cdcs WHERE id=?", (cdc_id,))
    try:
        if cdc["original_path"] and os.path.exists(cdc["original_path"]):
            os.unlink(cdc["original_path"])
    except OSError as exc:
        logger.warning("Failed to delete CDC file %s: %s", cdc["original_path"], exc)
    return True


# ---------------------------------------------------------------------------
# ANALYSES
# ---------------------------------------------------------------------------


def save_analysis(
    cdc_id: int,
    report: dict[str, Any],
    pipeline_version: str,
    corpus_fingerprint: str,
) -> int:
    """Persist an analysis report for a CDC. Returns the new analysis id."""
    summary = report.get("summary", {}) or {}
    created_at = _now_iso()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO analyses(
                cdc_id, created_at, total, covered, partial, missing, ambiguous,
                coverage_percent, chunks_processed, pipeline_version,
                corpus_fingerprint, report_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cdc_id,
                created_at,
                int(summary.get("total", 0)),
                int(summary.get("covered", 0)),
                int(summary.get("partial", 0)),
                int(summary.get("missing", 0)),
                int(summary.get("ambiguous", 0)),
                float(summary.get("coverage_percent", 0.0)),
                int(report.get("chunks_processed", 0)),
                pipeline_version,
                corpus_fingerprint,
                json.dumps(report, ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def get_latest_analysis(user_id: str, cdc_id: int) -> Optional[dict[str, Any]]:
    """Return the latest analysis (with full report) for a CDC owned by the user."""
    cdc = get_cdc(user_id, cdc_id)
    if not cdc:
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, cdc_id, created_at, total, covered, partial, missing,
                   ambiguous, coverage_percent, chunks_processed,
                   pipeline_version, corpus_fingerprint, report_json
            FROM analyses
            WHERE cdc_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (cdc_id,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        try:
            out["report"] = json.loads(out.pop("report_json"))
        except (TypeError, json.JSONDecodeError):
            out["report"] = None
        return out


# ---------------------------------------------------------------------------
# Status derivation (brouillon / analysé / périmé)
# ---------------------------------------------------------------------------


def derive_status(
    analysis_row: Optional[dict[str, Any]],
    current_pipeline_version: str,
    current_corpus_fingerprint: str,
) -> str:
    """Return one of: 'brouillon', 'analysé', 'périmé'."""
    if not analysis_row or analysis_row.get("analysis_id") is None:
        return "brouillon"
    pv = analysis_row.get("pipeline_version") or ""
    cf = analysis_row.get("corpus_fingerprint") or ""
    if pv != current_pipeline_version or cf != current_corpus_fingerprint:
        return "périmé"
    return "analysé"

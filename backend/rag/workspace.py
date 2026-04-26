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
  requirement_feedback(id, analysis_id, requirement_id, user_id, vote, comment,
                       created_at, updated_at)
    — v3.10.0, vote utilisateur 👍/👎 sur les exigences d'une analyse.

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

-- v3.10.0 — Boucle de feedback sur les exigences d'une analyse.
CREATE TABLE IF NOT EXISTS requirement_feedback (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL,
    requirement_id  TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    vote            TEXT NOT NULL CHECK(vote IN ('up','down')),
    comment         TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(analysis_id, requirement_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_req_feedback_analysis
    ON requirement_feedback(analysis_id);
CREATE INDEX IF NOT EXISTS idx_req_feedback_user
    ON requirement_feedback(analysis_id, user_id);
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


# ---------------------------------------------------------------------------
# v3.10.0 — Feedback sur les exigences d'une analyse
# ---------------------------------------------------------------------------

VALID_VOTES = {"up", "down"}
COMMENT_MAX_CHARS = 2000


def _feedback_id(analysis_id: str, requirement_id: str, user_id: str) -> str:
    """Identifiant déterministe (≤ 16 chars) pour une ligne de feedback."""
    raw = f"{analysis_id}|{requirement_id}|{user_id}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _user_owns_analysis(conn: sqlite3.Connection, user_id: str, analysis_id: int) -> bool:
    """Vérifie qu'une analyse appartient à l'un des clients de l'utilisateur."""
    row = conn.execute(
        """
        SELECT 1
        FROM analyses a
        JOIN cdcs    ON cdcs.id = a.cdc_id
        JOIN clients ON clients.id = cdcs.client_id
        WHERE a.id = ? AND clients.user_id = ?
        """,
        (analysis_id, user_id),
    ).fetchone()
    return bool(row)


def upsert_feedback(
    analysis_id: str,
    requirement_id: str,
    user_id: str,
    vote: str,
    comment: Optional[str] = None,
) -> dict[str, Any]:
    """INSERT OR REPLACE d'un feedback. Renvoie la ligne enregistrée."""
    if vote not in VALID_VOTES:
        raise ValueError(f"vote invalide : '{vote}' (attendu : 'up' ou 'down').")
    requirement_id = (requirement_id or "").strip()
    if not requirement_id:
        raise ValueError("requirement_id est requis.")
    analysis_id = str(analysis_id or "").strip()
    if not analysis_id:
        raise ValueError("analysis_id est requis.")
    cleaned_comment = (comment or "").strip()
    if cleaned_comment and len(cleaned_comment) > COMMENT_MAX_CHARS:
        cleaned_comment = cleaned_comment[:COMMENT_MAX_CHARS]
    fid = _feedback_id(analysis_id, requirement_id, user_id)
    now = _now_iso()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT created_at FROM requirement_feedback WHERE id = ?",
            (fid,),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT OR REPLACE INTO requirement_feedback(
                id, analysis_id, requirement_id, user_id,
                vote, comment, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                fid,
                analysis_id,
                requirement_id,
                user_id,
                vote,
                cleaned_comment or None,
                created_at,
                now,
            ),
        )
    return {
        "id": fid,
        "analysis_id": analysis_id,
        "requirement_id": requirement_id,
        "user_id": user_id,
        "vote": vote,
        "comment": cleaned_comment or None,
        "created_at": created_at,
        "updated_at": now,
    }


def delete_feedback(
    analysis_id: str,
    requirement_id: str,
    user_id: str,
) -> bool:
    """Supprime le feedback de cet utilisateur. Renvoie True si une ligne a été supprimée."""
    fid = _feedback_id(str(analysis_id), requirement_id, user_id)
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM requirement_feedback WHERE id = ?",
            (fid,),
        )
        return cur.rowcount > 0


def get_feedback(
    analysis_id: str,
    requirement_id: str,
    user_id: str,
) -> Optional[dict[str, Any]]:
    """Renvoie le feedback d'un utilisateur pour un requirement donné, ou None."""
    fid = _feedback_id(str(analysis_id), requirement_id, user_id)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, analysis_id, requirement_id, user_id, vote, comment,
                   created_at, updated_at
            FROM requirement_feedback
            WHERE id = ?
            """,
            (fid,),
        ).fetchone()
        return dict(row) if row else None


def list_feedback_for_analysis(analysis_id: str) -> list[dict[str, Any]]:
    """Tous les feedbacks pour une analyse (toutes user confondus)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, analysis_id, requirement_id, user_id, vote, comment,
                   created_at, updated_at
            FROM requirement_feedback
            WHERE analysis_id = ?
            ORDER BY updated_at DESC
            """,
            (str(analysis_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def get_feedback_stats(analysis_id: str) -> dict[str, Any]:
    """Agrégats simples pour le quality dashboard.

    Renvoie :
      - total_votes
      - up / down
      - top_contested : top 5 des requirements avec le plus de votes 'down'
      - feedback_per_domain : {category: {up: int, down: int}} dérivé du
        report stocké
      - coverage_corrected : recalcul de coverage avec ajustements feedback
        (down sur covered → -1, up sur missing → +1, etc.)
    """
    aid = str(analysis_id)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT requirement_id, vote
            FROM requirement_feedback
            WHERE analysis_id = ?
            """,
            (aid,),
        ).fetchall()
        votes = [(r["requirement_id"], r["vote"]) for r in rows]
        analysis_row = conn.execute(
            """
            SELECT report_json, total, covered, partial, missing, ambiguous
            FROM analyses
            WHERE id = ?
            """,
            (aid,),
        ).fetchone()

    total_votes = len(votes)
    up = sum(1 for _, v in votes if v == "up")
    down = sum(1 for _, v in votes if v == "down")

    # Top 5 contested = requirements avec le plus de 'down'.
    down_counts: dict[str, int] = {}
    for rid, v in votes:
        if v == "down":
            down_counts[rid] = down_counts.get(rid, 0) + 1
    top_contested = [
        {"requirement_id": rid, "down_votes": cnt}
        for rid, cnt in sorted(
            down_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]
    ]

    # Lecture du report pour ventilation par domaine + recalcul de coverage.
    feedback_per_domain: dict[str, dict[str, int]] = {}
    coverage_corrected: Optional[float] = None
    if analysis_row:
        try:
            report = json.loads(analysis_row["report_json"]) if analysis_row["report_json"] else {}
        except (TypeError, json.JSONDecodeError):
            report = {}
        reqs_by_id = {
            r.get("id"): r for r in (report.get("requirements") or []) if r.get("id")
        }
        for rid, vote in votes:
            req = reqs_by_id.get(rid)
            domain = (req or {}).get("category") or "Autre"
            bucket = feedback_per_domain.setdefault(domain, {"up": 0, "down": 0})
            bucket[vote] = bucket.get(vote, 0) + 1

        # Recalcul de coverage avec ajustements par feedback.
        # Règle simple : on ajuste la "valeur de couverture" attribuée à
        # chaque requirement (covered=1, partial=0.5, autre=0). Un down sur
        # un covered/partial le ramène à 0 ; un up sur missing/ambiguous le
        # passe à 1. Si plusieurs votes existent, on agrège (down domine
        # over up — les retours négatifs comptent davantage).
        votes_per_req: dict[str, dict[str, int]] = {}
        for rid, vote in votes:
            b = votes_per_req.setdefault(rid, {"up": 0, "down": 0})
            b[vote] += 1
        total = int(analysis_row["total"] or 0)
        if total > 0 and reqs_by_id:
            corrected_sum = 0.0
            for rid, req in reqs_by_id.items():
                base = (
                    1.0 if req.get("status") == "covered"
                    else 0.5 if req.get("status") == "partial"
                    else 0.0
                )
                vb = votes_per_req.get(rid, {"up": 0, "down": 0})
                if vb["down"] > 0 and base > 0:
                    base = 0.0
                elif vb["up"] > 0 and base < 1.0:
                    base = 1.0
                corrected_sum += base
            coverage_corrected = round(100.0 * corrected_sum / total, 1)

    return {
        "analysis_id": aid,
        "total_votes": total_votes,
        "up": up,
        "down": down,
        "top_contested": top_contested,
        "feedback_per_domain": feedback_per_domain,
        "coverage_corrected": coverage_corrected,
    }


def user_owns_analysis(user_id: str, analysis_id: str) -> bool:
    """Vérifie l'appartenance d'une analyse à l'utilisateur (chaîne client)."""
    try:
        aid = int(analysis_id)
    except (TypeError, ValueError):
        return False
    with _connect() as conn:
        return _user_owns_analysis(conn, user_id, aid)

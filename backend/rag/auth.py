"""
auth.py — SQLite user store for the RAG app (standalone + Docker modes).

Schema
------
users(username TEXT PK, email TEXT, name TEXT,
      hashed_password TEXT, created_at TIMESTAMP)

Password hashing uses bcrypt.

Usage
-----
    from rag.auth import register_user, verify_user, get_user
    from rag.auth import create_token, decode_token  # JWT helpers (re-exported)
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import USERS_DB_PATH
from .jwt_utils import create_token, decode_token  # re-export for convenience

logger = logging.getLogger(__name__)

# Use the configured path from config (can be overridden via DATA_DIR env var)
_DB_PATH = Path(USERS_DB_PATH)

_DDL = """
CREATE TABLE IF NOT EXISTS users (
    username        TEXT PRIMARY KEY,
    email           TEXT NOT NULL DEFAULT '',
    name            TEXT NOT NULL DEFAULT '',
    hashed_password TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _UserDB:
    """Internal singleton that manages the users SQLite file."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_DDL)
            self._conn.commit()

    def register(self, username: str, email: str, name: str, password: str) -> None:
        import bcrypt

        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO users(username, email, name, hashed_password, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (username.lower(), email, name, hashed, _now()),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"L'utilisateur '{username}' existe déjà.") from exc

    def verify(self, username: str, password: str) -> bool:
        import bcrypt

        with self._lock:
            cur = self._conn.execute(
                "SELECT hashed_password FROM users WHERE username=?",
                (username.lower(),),
            )
            row = cur.fetchone()
        if not row:
            return False
        return bcrypt.checkpw(password.encode(), row["hashed_password"].encode())

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT username, email, name, created_at FROM users WHERE username=?",
                (username.lower(),),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def all_users(self) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT username, email, name, hashed_password FROM users"
            )
            return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_db_instance: _UserDB | None = None
_db_lock = threading.Lock()


def _get_db() -> _UserDB:
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = _UserDB()
    return _db_instance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_user(username: str, email: str, name: str, password: str) -> None:
    """
    Register a new user.

    Raises ValueError if username already taken or if inputs are invalid.
    """
    username = username.strip()
    email = email.strip()
    name = name.strip()

    if not username:
        raise ValueError("Le nom d'utilisateur est requis.")
    if len(username) < 3:
        raise ValueError("Le nom d'utilisateur doit faire au moins 3 caractères.")
    if not password:
        raise ValueError("Le mot de passe est requis.")
    if len(password) < 6:
        raise ValueError("Le mot de passe doit faire au moins 6 caractères.")

    _get_db().register(username, email, name, password)


def verify_user(username: str, password: str) -> bool:
    """Return True if credentials are valid."""
    return _get_db().verify(username, password)


def get_user(username: str) -> dict[str, Any] | None:
    """Return user dict or None if not found."""
    return _get_db().get_user(username)


def list_users_for_authenticator() -> dict[str, Any]:
    """
    Return credentials in the format expected by streamlit-authenticator:

    {
        "usernames": {
            "alice": {
                "email": "alice@example.com",
                "name": "Alice Dupont",
                "password": "<bcrypt-hash>",
            },
            ...
        }
    }
    """
    users = _get_db().all_users()
    usernames: dict[str, Any] = {}
    for u in users:
        usernames[u["username"]] = {
            "email": u["email"],
            "name": u["name"],
            "password": u["hashed_password"],
        }
    return {"usernames": usernames}


# Re-export JWT helpers so callers can do: from rag.auth import create_token
__all__ = [
    "register_user",
    "verify_user",
    "get_user",
    "list_users_for_authenticator",
    "create_token",
    "decode_token",
]

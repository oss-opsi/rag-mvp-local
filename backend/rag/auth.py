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
from .crypto_utils import decrypt_str, encrypt_str
from .jwt_utils import create_token, decode_token  # re-export for convenience

logger = logging.getLogger(__name__)

# Use the configured path from config (can be overridden via DATA_DIR env var)
_DB_PATH = Path(USERS_DB_PATH)

_DDL = """
CREATE TABLE IF NOT EXISTS users (
    username           TEXT PRIMARY KEY,
    email              TEXT NOT NULL DEFAULT '',
    name               TEXT NOT NULL DEFAULT '',
    hashed_password    TEXT NOT NULL,
    created_at         TIMESTAMP NOT NULL,
    openai_api_key_enc TEXT NOT NULL DEFAULT ''
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
            # Migration: add openai_api_key_enc to existing tables
            cur = self._conn.execute("PRAGMA table_info(users)")
            cols = [r["name"] for r in cur.fetchall()]
            if "openai_api_key_enc" not in cols:
                self._conn.execute(
                    "ALTER TABLE users ADD COLUMN openai_api_key_enc TEXT NOT NULL DEFAULT ''"
                )
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

    def set_api_key(self, username: str, plaintext_key: str) -> None:
        """Encrypt and persist the OpenAI API key for a user."""
        enc = encrypt_str(plaintext_key) if plaintext_key else ""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE users SET openai_api_key_enc=? WHERE username=?",
                (enc, username.lower()),
            )
            if cur.rowcount == 0:
                raise ValueError(f"Utilisateur inconnu : {username}")
            self._conn.commit()

    def get_api_key(self, username: str) -> str:
        """Return the decrypted OpenAI API key (empty string if none)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT openai_api_key_enc FROM users WHERE username=?",
                (username.lower(),),
            )
            row = cur.fetchone()
        if not row or not row["openai_api_key_enc"]:
            return ""
        return decrypt_str(row["openai_api_key_enc"])

    def delete_api_key(self, username: str) -> None:
        """Clear the stored API key for a user."""
        with self._lock:
            self._conn.execute(
                "UPDATE users SET openai_api_key_enc='' WHERE username=?",
                (username.lower(),),
            )
            self._conn.commit()

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


def set_user_api_key(username: str, plaintext_key: str) -> None:
    """Persist the user's OpenAI API key (encrypted at rest)."""
    _get_db().set_api_key(username, plaintext_key)


def get_user_api_key(username: str) -> str:
    """Return the decrypted OpenAI API key for a user (empty string if none)."""
    return _get_db().get_api_key(username)


def delete_user_api_key(username: str) -> None:
    """Remove the stored API key for a user."""
    _get_db().delete_api_key(username)


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
    "set_user_api_key",
    "get_user_api_key",
    "delete_user_api_key",
    "list_users_for_authenticator",
    "create_token",
    "decode_token",
]

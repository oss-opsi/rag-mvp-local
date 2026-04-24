"""
history.py — SQLite-backed conversation history for the standalone RAG app.

Schema
------
conversations(id TEXT PK, user_id TEXT, title TEXT,
              created_at TIMESTAMP, updated_at TIMESTAMP)

messages(id INTEGER PK AUTOINCREMENT, conversation_id TEXT FK,
         role TEXT, content TEXT, sources_json TEXT,
         created_at TIMESTAMP)

Thread safety
-------------
Uses a threading.Lock so that Streamlit's concurrent reruns don't corrupt
the database.  The connection is created with check_same_thread=False.

Streamlit integration
---------------------
Call get_conversation_db() to get the singleton (cached via @st.cache_resource).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_DIR = Path("./data")
_DB_PATH = _DB_DIR / "conversations.db"

_DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT 'Nouvelle conversation',
    created_at  TIMESTAMP NOT NULL,
    updated_at  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    sources_json    TEXT,
    created_at      TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationDB:
    """Thread-safe SQLite wrapper for conversation persistence."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._lock = threading.Lock()
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_DDL)
            self._conn.commit()

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def create_conversation(self, user_id: str, title: str = "Nouvelle conversation") -> str:
        """Create a new conversation and return its id."""
        conv_id = str(uuid.uuid4())
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations(id, user_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conv_id, user_id, title, now, now),
            )
            self._conn.commit()
        return conv_id

    def rename_conversation(self, conv_id: str, title: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                (title, _now(), conv_id),
            )
            self._conn.commit()

    def delete_conversation(self, conv_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
            self._conn.commit()

    def list_conversations(self, user_id: str) -> list[dict[str, Any]]:
        """Return conversations for a user ordered by most recent first."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at,
                       COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                WHERE c.user_id = ?
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                """,
                (user_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: list[dict] | None = None,
    ) -> None:
        """Append a message to a conversation."""
        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages(conversation_id, role, content, sources_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, sources_json, now),
            )
            # Update conversation updated_at
            self._conn.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (now, conversation_id),
            )
            self._conn.commit()

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        """Return all messages in a conversation, ordered chronologically."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, role, content, sources_json, created_at "
                "FROM messages WHERE conversation_id=? ORDER BY id",
                (conversation_id,),
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d["sources_json"]:
                try:
                    d["sources"] = json.loads(d["sources_json"])
                except Exception:
                    d["sources"] = []
            else:
                d["sources"] = []
            del d["sources_json"]
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_conversation(self, conv_id: str) -> dict[str, Any]:
        """Return a JSON-serialisable dict for a full conversation."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, user_id, title, created_at, updated_at "
                "FROM conversations WHERE id=?",
                (conv_id,),
            )
            conv_row = cur.fetchone()
        if not conv_row:
            return {}
        messages = self.get_messages(conv_id)
        return {
            "id": conv_row["id"],
            "user_id": conv_row["user_id"],
            "title": conv_row["title"],
            "created_at": conv_row["created_at"],
            "updated_at": conv_row["updated_at"],
            "messages": messages,
        }

    # ------------------------------------------------------------------
    # Auto-title helper
    # ------------------------------------------------------------------

    @staticmethod
    def title_from_message(text: str, max_len: int = 60) -> str:
        """Derive a conversation title from the first user message."""
        clean = text.strip().replace("\n", " ")
        if len(clean) <= max_len:
            return clean
        return clean[:max_len].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------------------
# Streamlit singleton factory
# ---------------------------------------------------------------------------

def get_conversation_db() -> ConversationDB:
    """
    Return the singleton ConversationDB.
    Import and wrap with @st.cache_resource in the Streamlit app.
    """
    return ConversationDB()

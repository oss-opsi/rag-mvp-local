"""
settings.py — Application-wide key/value settings (SQLite).

Used to store admin-tunable values that should not require a redeploy:
  - llm_chat       : LLM model used by the chat / Q&A pipeline
  - llm_analysis   : LLM model used by the CDC gap analysis (first pass)
  - llm_repass     : LLM model used to re-evaluate ambiguous verdicts

Schema
------
app_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TIMESTAMP)
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import USERS_DB_PATH
from .crypto_utils import decrypt_str, encrypt_str

logger = logging.getLogger(__name__)

_DB_PATH = Path(USERS_DB_PATH)
_lock = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
"""

# Whitelisted models the UI exposes. Anything else is rejected at the API
# layer to avoid arbitrary strings being passed to ChatOpenAI.
ALLOWED_MODELS: tuple[str, ...] = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-5",
)

# Defaults applied when a setting has never been written.
DEFAULTS: dict[str, str] = {
    "llm_chat": "gpt-4o-mini",
    "llm_analysis": "gpt-4o-mini",
    "llm_repass": "gpt-4o",
}


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_settings_schema() -> None:
    """Create the table if it does not exist yet."""
    with _lock, _connect() as conn:
        conn.execute(_DDL)
        conn.commit()


def get_setting(key: str, default: str | None = None) -> str:
    """Return the stored value for `key`, or DEFAULTS[key], or `default`."""
    init_settings_schema()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    if row and row["value"]:
        return str(row["value"])
    if key in DEFAULTS:
        return DEFAULTS[key]
    return default or ""


def set_setting(key: str, value: str) -> None:
    """Insert or update a setting."""
    init_settings_schema()
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                            updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


def get_llm_settings() -> dict[str, str]:
    """Return the 3 LLM settings used by the app."""
    return {
        "llm_chat": get_setting("llm_chat"),
        "llm_analysis": get_setting("llm_analysis"),
        "llm_repass": get_setting("llm_repass"),
    }


def set_llm_settings(values: dict[str, str]) -> dict[str, str]:
    """
    Validate and persist the 3 LLM settings. Only keys present in `values`
    are updated. Unknown models are rejected. Returns the resulting state.
    """
    for key, val in values.items():
        if key not in DEFAULTS:
            raise ValueError(f"Clé inconnue : {key}")
        if val not in ALLOWED_MODELS:
            raise ValueError(
                f"Modèle non autorisé pour {key} : {val!r}. "
                f"Autorisés : {', '.join(ALLOWED_MODELS)}"
            )
        set_setting(key, val)
    return get_llm_settings()


# ---------------------------------------------------------------------------
# Lot 2 — Clés API tierces (chiffrées au repos via Fernet/JWT_SECRET)
# ---------------------------------------------------------------------------
#
# Convention : on stocke la valeur chiffrée dans app_settings sous une clé
# préfixée "secret.<provider>.<champ>". Le déchiffrement est explicite via
# get_secret() ; la valeur n'est jamais retournée en clair par les endpoints
# admin (cf. has_*/masked dans main.py).

LEGIFRANCE_CLIENT_ID_KEY = "secret.legifrance.client_id"
LEGIFRANCE_CLIENT_SECRET_KEY = "secret.legifrance.client_secret"


def set_secret(key: str, plaintext: str) -> None:
    """Stocke une valeur sensible chiffrée dans app_settings.

    Si plaintext est vide, supprime la valeur existante.
    """
    if not plaintext:
        # Effacer en écrivant une chaine vide (compat schéma : value NOT NULL)
        set_setting(key, "")
        return
    set_setting(key, encrypt_str(plaintext))


def get_secret(key: str) -> str:
    """Récupère et déchiffre une valeur sensible. Renvoie '' si absente."""
    raw = get_setting(key, default="")
    if not raw:
        return ""
    return decrypt_str(raw)


def has_secret(key: str) -> bool:
    """Indique si une valeur (non vide) est stockée pour cette clé."""
    return bool(get_setting(key, default=""))


def get_legifrance_credentials() -> tuple[str, str]:
    """Retourne (client_id, client_secret) en clair. ('', '') si absents."""
    return (
        get_secret(LEGIFRANCE_CLIENT_ID_KEY),
        get_secret(LEGIFRANCE_CLIENT_SECRET_KEY),
    )


def set_legifrance_credentials(client_id: str, client_secret: str) -> None:
    """Persiste les credentials PISTE chiffrés. Chaînes vides = effacement."""
    set_secret(LEGIFRANCE_CLIENT_ID_KEY, client_id)
    set_secret(LEGIFRANCE_CLIENT_SECRET_KEY, client_secret)

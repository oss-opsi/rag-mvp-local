"""crypto_utils.py — symmetric encryption helpers.

Fernet-based encryption keyed on JWT_SECRET (via HKDF-like derivation).
Used to store OpenAI API keys at rest in the users DB.

NEVER log ciphertext alongside plaintext.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    """Derive a stable Fernet key from JWT_SECRET.

    If JWT_SECRET is rotated, previously encrypted values become unreadable
    (which is the expected security property).
    """
    secret = os.getenv("JWT_SECRET", "insecure-dev-secret-change-me")
    # SHA-256 gives 32 bytes; Fernet requires urlsafe-base64 of 32 bytes.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_str(plaintext: str) -> str:
    """Encrypt a plaintext string and return base64 token (str)."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_str(token: str) -> str:
    """Decrypt a base64 token back to plaintext string.

    Returns empty string if the token is empty or invalid.
    """
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""

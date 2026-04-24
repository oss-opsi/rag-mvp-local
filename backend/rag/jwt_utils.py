"""
jwt_utils.py — JWT token creation and decoding for the RAG API.

Tokens are signed with HS256 and expire after JWT_EXPIRE_DAYS days.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from .config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET


def create_token(user_id: str, name: str = "") -> str:
    """Create a signed JWT for the given user_id."""
    payload = {
        "sub": user_id,
        "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT.

    Raises jwt.InvalidTokenError or jwt.ExpiredSignatureError on failure.
    Returns the payload dict on success.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

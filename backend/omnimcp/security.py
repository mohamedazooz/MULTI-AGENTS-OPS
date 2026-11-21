"""Security primitives: password hashing, API keys, JWT tokens, rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import settings

_hasher = PasswordHasher()
_revocation_window = max(30, settings.token_revocation_window_seconds)


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(hashed: str, plain: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def generate_key(prefix: str) -> tuple[str, str]:
    """Generate a random API key. Returns (plaintext, sha256 hash)."""
    raw = f"{prefix}_{secrets.token_urlsafe(32)}"
    return raw, sha256_hex(raw)


def create_jwt(
    sub: str,
    *,
    typ: str = "user",
    role: str = "",
    ttl_seconds: int | None = None,
    extra: dict | None = None,
) -> str:
    ttl = ttl_seconds if ttl_seconds is not None else settings.token_ttl_seconds
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "typ": typ,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    if role:
        payload["role"] = role
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict:
    """Decode and verify a JWT. Raises jwt.PyJWTError subclasses on failure."""
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub"]},
    )


def token_issued_recently(payload: dict, tolerance: int = 0) -> bool:
    """True if the token predates a user-level revocation timestamp."""
    iat = int(payload.get("iat", 0))
    return iat >= tolerance


_SYSTEM_FAILURES: dict[str, list[float]] = {}
_SYSTEM_LIMIT = 60  # attempts
_SYSTEM_WINDOW = 60.0  # seconds


def rate_limit_check(key: str, limit: int = _SYSTEM_LIMIT, window: float = _SYSTEM_WINDOW) -> bool:
    """Sliding window in-memory rate limiter. Returns True when allowed."""
    now = time.monotonic()
    bucket = [t for t in _SYSTEM_FAILURES.get(key, []) if now - t < window]
    if len(bucket) >= limit:
        _SYSTEM_FAILURES[key] = bucket
        return False
    bucket.append(now)
    _SYSTEM_FAILURES[key] = bucket
    return True


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)

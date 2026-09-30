from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass


PASSWORD_PREFIX = "scrypt"


def hash_password(password: str) -> str:
    """Create a portable scrypt password hash for APP_PASSWORD_HASH."""
    if not password or len(password) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"{PASSWORD_PREFIX}${encode(salt)}${encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        prefix, salt_text, digest_text = encoded.split("$", 2)
        if prefix != PASSWORD_PREFIX:
            return False
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        expected = decode(digest_text)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=decode(salt_text), n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Session:
    username: str
    expires_at: float


class SessionStore:
    def __init__(self, ttl_seconds: int = 8 * 60 * 60, secret: str | bytes | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self.secret = secret.encode("utf-8") if isinstance(secret, str) and secret else secret or secrets.token_bytes(32)
        self._sessions: dict[str, Session] = {}

    def create(self, username: str) -> str:
        self.purge_expired()
        nonce = secrets.token_bytes(32)
        signature = hmac.new(self.secret, nonce, hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(nonce + signature).decode("ascii").rstrip("=")
        self._sessions[token] = Session(username, time.time() + self.ttl_seconds)
        return token

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        session = self._sessions.get(token)
        if session is None or session.expires_at <= time.time():
            self._sessions.pop(token, None)
            return None
        return session

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def purge_expired(self) -> None:
        now = time.time()
        for token, session in list(self._sessions.items()):
            if session.expires_at <= now:
                self._sessions.pop(token, None)

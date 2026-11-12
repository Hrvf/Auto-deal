"""Mots de passe (scrypt), jetons CSRF, limitation des tentatives de connexion."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Le mot de passe doit contenir au moins 10 caractères.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


# Hash factice pour un temps de réponse constant quand l'utilisateur n'existe pas.
DUMMY_HASH = hash_password("mot-de-passe-factice-123")


def get_csrf_token(session: dict) -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def check_csrf(session: dict, submitted: str | None) -> bool:
    expected = session.get("csrf")
    return bool(expected and submitted and hmac.compare_digest(expected, submitted))


class LoginRateLimiter:
    """Bloque une IP après `max_attempts` échecs dans la fenêtre glissante."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._failures: dict[str, deque] = defaultdict(deque)

    def _prune(self, key: str) -> None:
        q = self._failures[key]
        now = time.monotonic()
        while q and now - q[0] > self.window:
            q.popleft()

    def is_blocked(self, key: str) -> bool:
        self._prune(key)
        return len(self._failures[key]) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


login_limiter = LoginRateLimiter()

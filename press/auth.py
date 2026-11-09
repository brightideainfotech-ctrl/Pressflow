"""Password hashing, sessions and login throttling (standard library only)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import timedelta

from . import db

PBKDF2_ITERATIONS = 200_000
SESSION_DAYS = 7
MIN_PASSWORD = 8
ROLES = ("manager", "desk", "superintendent", "operator")


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, digest = hash_password(password, salt_hex)
    return hmac.compare_digest(digest, hash_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user(conn, username: str, name: str, role: str, password: str) -> int:
    if role not in ROLES:
        raise ValueError("Unknown role")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")
    salt, digest = hash_password(password)
    cur = conn.execute(
        "INSERT INTO users(username,name,role,salt,pw_hash,created_at) VALUES(?,?,?,?,?,?)",
        (username.strip(), name.strip(), role, salt, digest, db.stamp()),
    )
    return cur.lastrowid


def start_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    created = db.now()
    conn.execute(
        "INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
        (_token_hash(token), user_id, created.strftime("%Y-%m-%d %H:%M:%S"),
         (created + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (db.stamp(),))
    return token


def user_for_token(conn, token: str):
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id,u.username,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
        (_token_hash(token), db.stamp()),
    ).fetchone()
    return dict(row) if row else None


def end_session(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


def end_all_sessions(conn, user_id: int, keep_token: str | None = None) -> None:
    if keep_token:
        conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user_id, _token_hash(keep_token)))
    else:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


class LoginThrottle:
    """Allow a handful of failed logins per (address, username) in a time window."""

    def __init__(self, limit: int = 8, window: int = 600):
        self.limit, self.window = limit, window
        self._fails: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key):
        cutoff = time.time() - self.window
        self._fails[key] = [t for t in self._fails.get(key, []) if t > cutoff]
        return self._fails[key]

    def blocked(self, addr: str, username: str) -> bool:
        with self._lock:
            return len(self._recent((addr, username.lower()))) >= self.limit

    def failed(self, addr: str, username: str) -> None:
        with self._lock:
            self._recent((addr, username.lower())).append(time.time())

    def ok(self, addr: str, username: str) -> None:
        with self._lock:
            self._fails.pop((addr, username.lower()), None)

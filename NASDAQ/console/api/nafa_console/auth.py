"""Authentication (docs/08 §9): one owner, optional read-only viewers.

* Passwords: argon2id. Second factor: TOTP (RFC 6238, 6 digits, 30 s).
* Sessions: random token in an httpOnly, SameSite=Strict cookie (Secure
  when served over TLS); the database keeps only its SHA-256. 12 h idle
  timeout. Every POST needs the session's CSRF token in X-CSRF-Token.
* Login is rate-limited: 5 failures lock the account for 15 minutes.
* Step-up: a control action carries a fresh TOTP code, checked again here;
  a code is accepted once (replay-protected per user).
* Every login, failure, lockout and step-up lands in auth_event.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import sqlite3
import threading
from dataclasses import dataclass

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

SESSION_COOKIE = "nafa_session"
IDLE_TIMEOUT = dt.timedelta(hours=12)
MAX_FAILURES = 5
LOCKOUT = dt.timedelta(minutes=15)
STEP_UP_WINDOW = dt.timedelta(minutes=5)
ROLES = ("owner", "viewer")

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
  username      TEXT PRIMARY KEY,
  role          TEXT NOT NULL CHECK (role IN ('owner', 'viewer')),
  password_hash TEXT NOT NULL,
  totp_secret   TEXT NOT NULL,
  failures      INTEGER NOT NULL DEFAULT 0,
  locked_until  TEXT,
  last_totp_step INTEGER NOT NULL DEFAULT 0,
  created_utc   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_session (
  token_hash  TEXT PRIMARY KEY,
  username    TEXT NOT NULL REFERENCES app_user(username) ON DELETE CASCADE,
  csrf        TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  seen_utc    TEXT NOT NULL,
  totp_utc    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_event (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  at_utc   TEXT NOT NULL,
  username TEXT,
  event    TEXT NOT NULL,
  detail   TEXT NOT NULL DEFAULT ''
);
"""

_ph = PasswordHasher()


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def parse(s: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(s) if s else None


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Session:
    username: str
    role: str
    csrf: str
    totp_at: dt.datetime

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Auth:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self.db = db
        self.lock = lock
        with lock:
            db.executescript(SCHEMA)
            db.commit()

    # ── users ──
    def has_users(self) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM app_user LIMIT 1").fetchone() is not None

    def add_user(self, username: str, password: str, role: str = "owner") -> str:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if len(password) < 12:
            raise ValueError("use a password of at least 12 characters")
        secret = pyotp.random_base32()
        with self.lock:
            self.db.execute("INSERT INTO app_user(username, role, password_hash, totp_secret, created_utc) VALUES (?,?,?,?,?)",
                            (username, role, _ph.hash(password), secret, iso(now())))
            self.db.commit()
        self.event(username, "user_added", role)
        return secret

    def set_password(self, username: str, password: str) -> None:
        if len(password) < 12:
            raise ValueError("use a password of at least 12 characters")
        with self.lock:
            n = self.db.execute("UPDATE app_user SET password_hash=?, failures=0, locked_until=NULL WHERE username=?",
                                (_ph.hash(password), username)).rowcount
            self.db.execute("DELETE FROM app_session WHERE username=?", (username,))
            self.db.commit()
        if not n:
            raise KeyError(username)
        self.event(username, "password_set")

    def reset_totp(self, username: str) -> str:
        secret = pyotp.random_base32()
        with self.lock:
            n = self.db.execute("UPDATE app_user SET totp_secret=?, last_totp_step=0 WHERE username=?", (secret, username)).rowcount
            self.db.execute("DELETE FROM app_session WHERE username=?", (username,))
            self.db.commit()
        if not n:
            raise KeyError(username)
        self.event(username, "totp_reset")
        return secret

    def remove_user(self, username: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM app_session WHERE username=?", (username,))
            self.db.execute("DELETE FROM app_user WHERE username=?", (username,))
            self.db.commit()
        self.event(username, "user_removed")

    def users(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT username, role, created_utc, failures, locked_until FROM app_user ORDER BY username").fetchall()
        return [dict(zip(("username", "role", "created", "failures", "locked_until"), r)) for r in rows]

    @staticmethod
    def otpauth_uri(username: str, secret: str) -> str:
        return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="NAFA Console")

    # ── events ──
    def event(self, username: str | None, event: str, detail: str = "") -> None:
        with self.lock:
            self.db.execute("INSERT INTO auth_event(at_utc, username, event, detail) VALUES (?,?,?,?)", (iso(now()), username, event, detail[:300]))
            self.db.commit()

    def events(self, limit: int = 200) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT at_utc, username, event, detail FROM auth_event ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(("at", "user", "event", "detail"), r)) for r in rows]

    # ── TOTP ──
    def check_totp(self, username: str, code: str) -> bool:
        """Valid for the current step ±1, and each step only once."""
        code = (code or "").replace(" ", "")
        if not (code.isdigit() and len(code) == 6):
            return False
        with self.lock:
            row = self.db.execute("SELECT totp_secret, last_totp_step FROM app_user WHERE username=?", (username,)).fetchone()
        if not row:
            return False
        totp = pyotp.TOTP(row[0])
        t = now().timestamp()
        for drift in (0, -1, 1):
            step = int(t // 30) + drift
            if totp.at(step * 30) == code:
                if step <= row[1]:
                    return False  # already used: replay
                with self.lock:
                    self.db.execute("UPDATE app_user SET last_totp_step=? WHERE username=?", (step, username))
                    self.db.commit()
                return True
        return False

    # ── login / sessions ──
    def login(self, username: str, password: str, code: str) -> tuple[str, Session]:
        with self.lock:
            row = self.db.execute("SELECT role, password_hash, failures, locked_until FROM app_user WHERE username=?", (username,)).fetchone()
        if not row:
            self.event(username, "login_failed", "unknown user")
            raise AuthError(401, "Wrong username, password or code.")
        role, pw_hash, failures, locked_until = row
        lu = parse(locked_until)
        if lu and lu > now():
            self.event(username, "login_locked")
            raise AuthError(429, f"Too many failed attempts. Try again after {lu.astimezone().strftime('%H:%M')}.")
        try:
            _ph.verify(pw_hash, password)
            pw_ok = True
        except (VerificationError, InvalidHashError):
            pw_ok = False
        if not pw_ok or not self.check_totp(username, code):
            failures += 1
            locked = iso(now() + LOCKOUT) if failures >= MAX_FAILURES else None
            with self.lock:
                self.db.execute("UPDATE app_user SET failures=?, locked_until=? WHERE username=?",
                                (0 if locked else failures, locked, username))
                self.db.commit()
            self.event(username, "login_failed", "locked for 15 min" if locked else f"failure {failures}")
            raise AuthError(401, "Wrong username, password or code.")
        if _ph.check_needs_rehash(pw_hash):
            with self.lock:
                self.db.execute("UPDATE app_user SET password_hash=? WHERE username=?", (_ph.hash(password), username))
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        t = iso(now())
        with self.lock:
            self.db.execute("UPDATE app_user SET failures=0, locked_until=NULL WHERE username=?", (username,))
            self.db.execute("INSERT INTO app_session(token_hash, username, csrf, created_utc, seen_utc, totp_utc) VALUES (?,?,?,?,?,?)",
                            (_h(token), username, csrf, t, t, t))
            self.db.commit()
        self.event(username, "login")
        return token, Session(username, role, csrf, now())

    def session(self, token: str | None) -> Session | None:
        if not token:
            return None
        with self.lock:
            row = self.db.execute("SELECT s.username, u.role, s.csrf, s.seen_utc, s.totp_utc FROM app_session s JOIN app_user u USING(username) WHERE s.token_hash=?",
                                  (_h(token),)).fetchone()
            if not row:
                return None
            seen = parse(row[3])
            if seen and now() - seen > IDLE_TIMEOUT:
                self.db.execute("DELETE FROM app_session WHERE token_hash=?", (_h(token),))
                self.db.commit()
                return None
            self.db.execute("UPDATE app_session SET seen_utc=? WHERE token_hash=?", (iso(now()), _h(token)))
            self.db.commit()
        return Session(row[0], row[1], row[2], parse(row[4]) or now())

    def step_up(self, token: str, sess: Session, code: str) -> None:
        if not self.check_totp(sess.username, code):
            self.event(sess.username, "stepup_failed")
            raise AuthError(403, "The authenticator code is wrong or already used.")
        with self.lock:
            self.db.execute("UPDATE app_session SET totp_utc=? WHERE token_hash=?", (iso(now()), _h(token)))
            self.db.commit()
        self.event(sess.username, "stepup")

    def logout(self, token: str | None) -> None:
        if token:
            with self.lock:
                self.db.execute("DELETE FROM app_session WHERE token_hash=?", (_h(token),))
                self.db.commit()

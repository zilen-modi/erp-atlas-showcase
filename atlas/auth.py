"""People: Atlas accounts, sign-in sessions, roles, and each person's own Claude.

Two roles. An *admin* manages users and settings, refreshes the index, and reviews facts (accepts or retires
them -- the named human the fact lifecycle asks for). A *member* uses everything else.

Passwords are scrypt hashes. A signed-in browser holds a random token in an HttpOnly cookie; only its hash is
stored. Each person connects their own Claude subscription (a `claude setup-token` token) so Ask Atlas and "Write
criteria" run on their plan; API keys are not accepted, so nothing is billed per call. Tokens are encrypted with a
key kept in .data/.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from atlas.config import ROOT
from atlas.store.db import Store, now

Result = dict[str, Any]
ROLES = ("admin", "member")
SESSION_DAYS = 14
COOKIE = "atlas_session"
KEY_FILE = ROOT / ".data" / "secret.key"
_SCRYPT = (2**14, 8, 1)


class AuthError(ValueError):
    pass


# ------------------------------------------------------------------ passwords and secrets

def hash_password(pw: str) -> str:
    if len(pw) < 8:
        raise AuthError("Use at least 8 characters")
    n, r, p = _SCRYPT
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError):
        return False


def _fernet(path: Path = KEY_FILE) -> Fernet:
    """The server's key for secrets at rest, made on first use and readable only by its owner."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Fernet.generate_key())
        os.chmod(path, 0o600)
    return Fernet(path.read_bytes())


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def audit(store: Store, user_id: str | None, action: str, detail: Result | None = None) -> None:
    store.db.execute("INSERT INTO audit VALUES (?,?,?,?)", (now(), user_id, action, json.dumps(detail or {})))
    store.commit()


def test_reads_today(store: Store, user_id: str, via: str | None = None) -> int:
    """How many TEST reads this person made since midnight UTC (all, or by one route: ask-atlas / test-data)."""
    sql = "SELECT COUNT(*) n FROM audit WHERE action='test.read' AND user_id=? AND at >= ?"
    args: list[Any] = [user_id, datetime.now(UTC).strftime("%Y-%m-%dT00:00:00")]
    if via:
        sql += " AND json_extract(detail, '$.via') = ?"
        args.append(via)
    return int(store.db.execute(sql, args).fetchone()["n"])


# ------------------------------------------------------------------ users

def _public(r: Any) -> Result:
    return {"id": r["id"], "email": r["email"], "name": r["name"], "role": r["role"], "active": bool(r["active"]),
            "must_change": bool(r["must_change"]), "created_at": r["created_at"], "last_login": r["last_login"]}


def count_users(store: Store) -> int:
    return int(store.db.execute("SELECT COUNT(*) n FROM app_user").fetchone()["n"])


def list_users(store: Store) -> list[Result]:
    rows = store.db.execute("SELECT u.*, c.kind claude_kind, c.hint claude_hint FROM app_user u "
                            "LEFT JOIN user_claude c ON c.user_id = u.id ORDER BY u.role, u.name").fetchall()
    return [{**_public(r), "claude": {"kind": r["claude_kind"], "hint": r["claude_hint"]} if r["claude_kind"] else None}
            for r in rows]


def get_user(store: Store, user_id: str) -> Result | None:
    r = store.db.execute("SELECT * FROM app_user WHERE id=?", (user_id,)).fetchone()
    return _public(r) if r else None


def create_user(store: Store, email: str, name: str, role: str, password: str | None = None,
                by: str | None = None) -> tuple[Result, str | None]:
    """A new account. Without a password one is generated, shown once, and must be changed at first sign-in."""
    email, name = email.strip().lower(), name.strip()
    if "@" not in email or not name:
        raise AuthError("A user needs a name and an email address")
    if role not in ROLES:
        raise AuthError(f"Role must be one of {', '.join(ROLES)}")
    if store.db.execute("SELECT 1 FROM app_user WHERE email=?", (email,)).fetchone():
        raise AuthError(f"{email} already has an account")
    temp = None if password else secrets.token_urlsafe(9)
    uid = uuid.uuid4().hex[:12]
    store.db.execute("INSERT INTO app_user VALUES (?,?,?,?,?,1,?,?,NULL)",
                     (uid, email, name, role, hash_password(password or temp or ""), 1 if temp else 0, now()))
    store.commit()
    audit(store, by, "user.create", {"user": uid, "email": email, "role": role})
    return get_user(store, uid) or {}, temp


def update_user(store: Store, user_id: str, by: str, role: str | None = None, active: bool | None = None,
                name: str | None = None) -> Result:
    u = get_user(store, user_id)
    if not u:
        raise AuthError("No such user")
    if role is not None and role not in ROLES:
        raise AuthError(f"Role must be one of {', '.join(ROLES)}")
    # never leave Atlas without an active admin
    losing = (role is not None and role != "admin") or active is False
    if u["role"] == "admin" and u["active"] and losing and _active_admins(store) <= 1:
        raise AuthError("This is the last active admin: make someone else an admin first")
    if role is not None:
        store.db.execute("UPDATE app_user SET role=? WHERE id=?", (role, user_id))
    if active is not None:
        store.db.execute("UPDATE app_user SET active=? WHERE id=?", (1 if active else 0, user_id))
        if not active:
            store.db.execute("DELETE FROM app_session WHERE user_id=?", (user_id,))
    if name:
        store.db.execute("UPDATE app_user SET name=? WHERE id=?", (name.strip(), user_id))
    store.commit()
    audit(store, by, "user.update", {"user": user_id, "role": role, "active": active, "name": name})
    return get_user(store, user_id) or {}


def _active_admins(store: Store) -> int:
    return int(store.db.execute("SELECT COUNT(*) n FROM app_user WHERE role='admin' AND active=1").fetchone()["n"])


def reset_password(store: Store, user_id: str, by: str) -> str:
    """A new temporary password for someone who forgot theirs; they choose their own at next sign-in."""
    if not get_user(store, user_id):
        raise AuthError("No such user")
    temp = secrets.token_urlsafe(9)
    store.db.execute("UPDATE app_user SET password=?, must_change=1 WHERE id=?", (hash_password(temp), user_id))
    store.db.execute("DELETE FROM app_session WHERE user_id=?", (user_id,))
    store.commit()
    audit(store, by, "user.reset_password", {"user": user_id})
    return temp


def change_password(store: Store, user_id: str, current: str, new: str) -> None:
    r = store.db.execute("SELECT password FROM app_user WHERE id=?", (user_id,)).fetchone()
    if not r or not check_password(current, r["password"]):
        raise AuthError("Your current password isn't right")
    store.db.execute("UPDATE app_user SET password=?, must_change=0 WHERE id=?", (hash_password(new), user_id))
    store.commit()
    audit(store, user_id, "user.change_password")


# ------------------------------------------------------------------ sessions

LOCKOUT_MIN = 15          # after too many wrong passwords, sign-in waits this long
MAX_FAILS_EMAIL = 5       # wrong passwords for one account within the window
MAX_FAILS_IP = 20         # wrong passwords from one address within the window (guessing many accounts)


def _recent_fails(store: Store, key: str, value: str) -> int:
    since = (datetime.now(UTC) - timedelta(minutes=LOCKOUT_MIN)).isoformat(timespec="seconds")
    return int(store.db.execute("SELECT COUNT(*) n FROM audit WHERE action='login.failed' AND at >= ? "
                                f"AND json_extract(detail, '$.{key}') = ?", (since, value)).fetchone()["n"])


def login(store: Store, email: str, password: str, ip: str | None = None) -> tuple[str, Result]:
    email = email.strip().lower()
    locked = _recent_fails(store, "email", email) >= MAX_FAILS_EMAIL
    if locked or (ip and _recent_fails(store, "ip", ip) >= MAX_FAILS_IP):
        audit(store, None, "login.locked", {"email": email, "ip": ip})
        raise AuthError(f"Too many wrong passwords. Wait {LOCKOUT_MIN} minutes, or ask an admin to reset yours.")
    r = store.db.execute("SELECT * FROM app_user WHERE email=?", (email,)).fetchone()
    if not r or not r["active"] or not check_password(password, r["password"]):
        audit(store, None, "login.failed", {"email": email, "ip": ip})
        raise AuthError("Wrong email or password")
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(UTC) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    store.db.execute("INSERT INTO app_session VALUES (?,?,?,?,?)", (_sha(token), r["id"], now(), expires, now()))
    store.db.execute("UPDATE app_user SET last_login=? WHERE id=?", (now(), r["id"]))
    store.commit()
    audit(store, r["id"], "login")
    return token, _public(r)


def session_user(store: Store, token: str | None) -> Result | None:
    """The signed-in person for a cookie token, or None (unknown, expired, or deactivated)."""
    if not token:
        return None
    r = store.db.execute("SELECT u.*, s.expires_at FROM app_session s JOIN app_user u ON u.id = s.user_id "
                         "WHERE s.token_hash=?", (_sha(token),)).fetchone()
    if not r or not r["active"] or r["expires_at"] < now():
        return None
    return _public(r)


def render_session(store: Store, user_id: str, minutes: int = 5) -> str:
    """A short sign-in for the server's own headless browser to load a page as this person (a PDF export).
    The caller ends it with logout() as soon as the page is printed."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    store.db.execute("INSERT INTO app_session VALUES (?,?,?,?,?)", (_sha(token), user_id, now(), expires, now()))
    store.commit()
    return token


def logout(store: Store, token: str | None) -> None:
    if token:
        store.db.execute("DELETE FROM app_session WHERE token_hash=?", (_sha(token),))
        store.commit()


# ------------------------------------------------------------------ each person's Claude

def set_claude(store: Store, user_id: str, kind: str, secret: str) -> Result:
    secret = "".join(secret.split())     # a terminal wraps the long token; copying it brings the line break along
    if kind != "subscription" or secret.startswith("sk-ant-api"):
        raise AuthError("Atlas runs on Claude subscriptions only, not API keys: run `claude setup-token` and paste "
                        "the token it prints (it starts sk-ant-oat01-)")
    if len(secret) < 20:
        raise AuthError("That doesn't look like a complete token")
    hint = f"…{secret[-4:]}"
    store.db.execute("INSERT OR REPLACE INTO user_claude VALUES (?,?,?,?,?,NULL)",
                     (user_id, kind, _fernet().encrypt(secret.encode()).decode(), hint, now()))
    store.commit()
    audit(store, user_id, "claude.connect", {"kind": kind})
    return {"kind": kind, "hint": hint}


def get_claude(store: Store, user_id: str) -> Result | None:
    r = store.db.execute("SELECT kind, hint, added_at, last_used FROM user_claude WHERE user_id=?",
                         (user_id,)).fetchone()
    return dict(r) if r else None


def remove_claude(store: Store, user_id: str) -> None:
    store.db.execute("DELETE FROM user_claude WHERE user_id=?", (user_id,))
    store.commit()
    audit(store, user_id, "claude.disconnect")


def claude_env(store: Store, user_id: str | None, allow_shared: bool) -> dict[str, str]:
    """Environment for running Claude Code as this person: their own token or key, and their own config dir
    (so their sessions and history stay theirs). With no connection, the server's own login if allowed."""
    if user_id:
        r = store.db.execute("SELECT kind, secret FROM user_claude WHERE user_id=?", (user_id,)).fetchone()
        if r:
            try:
                secret = _fernet().decrypt(r["secret"].encode()).decode()
            except InvalidToken as e:
                raise AuthError("Your saved Claude connection can't be read any more: connect it again") from e
            store.db.execute("UPDATE user_claude SET last_used=? WHERE user_id=?", (now(), user_id))
            store.commit()
            home = ROOT / ".data" / "claude" / user_id
            home.mkdir(parents=True, exist_ok=True)
            os.chmod(home, 0o700)               # their Claude sessions: readable by the server's user only
            if r["kind"] != "subscription":
                raise AuthError("Atlas no longer takes API keys: connect your Claude subscription (Account → Claude)")
            return {"CLAUDE_CODE_OAUTH_TOKEN": secret, "CLAUDE_CONFIG_DIR": str(home)}
    if allow_shared:
        return {}
    raise AuthError("Connect your Claude account first (Account → Claude): Ask Atlas runs on your own Claude.")


# ------------------------------------------------------------------ preferences

def get_pref(store: Store, user_id: str, key: str) -> str | None:
    r = store.db.execute("SELECT value FROM user_pref WHERE user_id=? AND key=?", (user_id, key)).fetchone()
    return r["value"] if r else None


def set_pref(store: Store, user_id: str, key: str, value: str | None) -> None:
    if value in (None, ""):
        store.db.execute("DELETE FROM user_pref WHERE user_id=? AND key=?", (user_id, key))
    else:
        store.db.execute("INSERT OR REPLACE INTO user_pref VALUES (?,?,?)", (user_id, key, value))
    store.commit()


def fingerprint(user: Result | None) -> str:
    """How a person is named in facts, feedback and answers."""
    return f"{user['name']} <{user['email']}>" if user else "anonymous"


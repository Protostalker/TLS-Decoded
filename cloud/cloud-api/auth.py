"""
Auth helpers — two independent credential types (CLOUD-ARCHITECTURE.md):

1. Station device credential (machine-to-machine): device_id + device_secret,
   checked against `stations`, used only by the sync service against the
   Ingest API. Verified with `verify_device`.

2. User login (human): email + password against `users`, producing a
   DB-backed session row in `sessions` (not a JWT — see the design doc for
   why: 'never expires' + admin revocation together rule out stateless
   tokens). Verified with `get_current_user` / `require_admin`.

Rotating or revoking one type never touches the other.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models import CloudLicenseState, Station, UserSession, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_secret(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_secret(raw: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(raw, hashed)
    except Exception:
        return False


def gen_device_id() -> str:
    return "stn_" + secrets.token_hex(8)


def gen_device_secret() -> str:
    return secrets.token_urlsafe(32)


# ── Session tokens ────────────────────────────────────────────────────────────
# Tokens are stored hashed (SHA-256 is fine here — the token itself is 256
# bits of CSPRNG entropy, so this isn't a low-entropy-secret situation like a
# password; the hash just keeps a stolen DB from handing over live sessions).

def gen_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


SESSION_DURATIONS = {
    "short": timedelta(hours=12),   # default — "until the session ends", approximated as 12h idle
    "90d": timedelta(days=90),
    "never": None,
}


def create_session(
    db: Session, user: User, duration: str, user_agent: Optional[str], ip_address: Optional[str]
) -> str:
    if duration not in SESSION_DURATIONS:
        duration = "short"
    now = datetime.now(tz=timezone.utc)
    delta = SESSION_DURATIONS[duration]
    token = gen_session_token()
    sess = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        created_at=now,
        expires_at=(now + delta) if delta else None,
        last_used_at=now,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(sess)
    db.commit()
    return token


def _extract_token(request: Request, authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get("session_token")


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
) -> User:
    token = _extract_token(request, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_hash = hash_token(token)
    sess = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")
    if sess.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Session revoked")
    now = datetime.now(tz=timezone.utc)
    expires_at = sess.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:  # defensive: DB driver returned a naive datetime
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise HTTPException(status_code=401, detail="Session expired")

    user = db.query(User).filter(User.id == sess.user_id).first()
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="User inactive")

    sess.last_used_at = now
    db.commit()
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# ── License-degraded gating ──────────────────────────────────────────────────
# Per the dev handoff doc's open-question answer: in degraded mode (Annual
# license unreachable/invalid for 45+ consecutive days), admin users keep
# full functionality; everyone else (user/supplier roles) loses ALL data
# visibility, not just ordering/reports. Applied as a router-level dependency
# on stations.py/supplier.py/notifications.py/push.py — see their `router =
# APIRouter(dependencies=[...])` lines. Historical data is never deleted;
# this only blocks serving it to non-admins while degraded.

DEGRADED_DETAIL = (
    "This account's Cloud Utility license needs attention — data access is "
    "limited to admins until it's resolved. Ask an admin to check Settings -> License."
)


def require_not_degraded(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if user.role == "admin":
        return user
    state = db.query(CloudLicenseState).filter(CloudLicenseState.id == 1).first()
    if state and state.status == "degraded":
        raise HTTPException(status_code=403, detail=DEGRADED_DETAIL)
    return user


# ── Device auth (station -> Ingest API) ─────────────────────────────────────

def verify_device(
    db: Session = Depends(get_db),
    x_station_device_id: Optional[str] = Header(None),
    x_station_device_secret: Optional[str] = Header(None),
) -> Station:
    if not x_station_device_id or not x_station_device_secret:
        raise HTTPException(status_code=401, detail="Missing device credentials")
    station = db.query(Station).filter(Station.device_id == x_station_device_id).first()
    if not station or not station.active:
        raise HTTPException(status_code=401, detail="Unknown or inactive station")
    if not verify_secret(x_station_device_secret, station.device_secret_hash):
        raise HTTPException(status_code=401, detail="Invalid device credential")
    return station


# ── Station access scoping (T1/T2) ──────────────────────────────────────────

def assigned_station_ids(db: Session, user: User) -> list[int]:
    if user.role == "admin":
        rows = db.execute(text("SELECT id FROM stations WHERE active = TRUE")).fetchall()
        return [r[0] for r in rows]
    rows = db.execute(
        text(
            "SELECT s.id FROM stations s "
            "JOIN user_station_assignments a ON a.station_id = s.id "
            "WHERE a.user_id = :uid AND s.active = TRUE"
        ),
        {"uid": user.id},
    ).fetchall()
    return [r[0] for r in rows]


def require_station_access(station_id: int, db: Session, user: User) -> Station:
    if station_id not in assigned_station_ids(db, user):
        raise HTTPException(status_code=404, detail="Station not found")
    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    return station

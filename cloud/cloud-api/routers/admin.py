"""
T3 — internal admin portal API (served at a distinct path, e.g. /admin, by
the frontend; every route here additionally requires role=admin).

Admins: create customers, provision stations (issuing the device credential
shown exactly once), create/manage users, assign users to stations, rotate
station credentials, and view/revoke any user's sessions.
"""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import gen_device_id, gen_device_secret, hash_secret, require_admin
from database import get_db
from models import Customer, Station, User, UserSession, UserStationAssignment
from schemas import (
    AssignmentCreate, CustomerCreate, CustomerOut, SessionOut, StationCreate,
    StationCredentialOut, StationOut, StationUpdate, UserCreate, UserOut, UserUpdate,
)

router = APIRouter(dependencies=[Depends(require_admin)])


# ── Customers ─────────────────────────────────────────────────────────────────

@router.get("/admin/customers", response_model=list[CustomerOut])
def list_customers(db: Session = Depends(get_db)):
    customers = db.query(Customer).order_by(Customer.name).all()
    out = []
    for c in customers:
        station_count = db.query(Station).filter(Station.customer_id == c.id).count()
        user_count = db.query(User).filter(User.customer_id == c.id).count()
        out.append(CustomerOut(
            id=c.id, name=c.name, plan=c.plan, created_at=c.created_at,
            station_count=station_count, user_count=user_count,
        ))
    return out


@router.post("/admin/customers", response_model=CustomerOut)
def create_customer(body: CustomerCreate, db: Session = Depends(get_db)):
    c = Customer(name=body.name, plan=body.plan, created_at=datetime.now(tz=timezone.utc))
    db.add(c)
    db.commit()
    db.refresh(c)
    return CustomerOut(id=c.id, name=c.name, plan=c.plan, created_at=c.created_at, station_count=0, user_count=0)


# ── Stations ──────────────────────────────────────────────────────────────────

def _station_out(db: Session, s: Station) -> StationOut:
    cust = db.query(Customer).filter(Customer.id == s.customer_id).first()
    return StationOut(
        id=s.id, name=s.name, customer_id=s.customer_id, customer_name=cust.name if cust else None,
        sync_interval_minutes=s.sync_interval_minutes, last_sync_at=s.last_sync_at, active=s.active,
        zip_code=s.zip_code, timezone=s.timezone,
    )


@router.get("/admin/stations", response_model=list[StationOut])
def list_stations(db: Session = Depends(get_db)):
    stations = db.query(Station).order_by(Station.name).all()
    return [_station_out(db, s) for s in stations]


@router.post("/admin/stations", response_model=StationCredentialOut)
def create_station(body: StationCreate, db: Session = Depends(get_db)):
    """Provision a new station. Returns the device credential — the ONLY time
    the raw device_secret is ever returned; only its hash is stored."""
    if not db.query(Customer).filter(Customer.id == body.customer_id).first():
        raise HTTPException(status_code=404, detail="Customer not found")

    device_id = gen_device_id()
    device_secret = gen_device_secret()
    s = Station(
        customer_id=body.customer_id, name=body.name, device_id=device_id,
        device_secret_hash=hash_secret(device_secret),
        sync_interval_minutes=body.sync_interval_minutes,
        zip_code=(body.zip_code.strip() if body.zip_code else None),
        timezone=(body.timezone.strip() if body.timezone else None),
        active=True, created_at=datetime.now(tz=timezone.utc),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return StationCredentialOut(station_id=s.id, device_id=device_id, device_secret=device_secret)


@router.put("/admin/stations/{station_id}", response_model=StationOut)
def update_station(station_id: int, body: StationUpdate, db: Session = Depends(get_db)):
    s = db.query(Station).filter(Station.id == station_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Station not found")
    if body.name is not None:
        s.name = body.name
    if body.sync_interval_minutes is not None:
        if body.sync_interval_minutes < 1:
            raise HTTPException(status_code=400, detail="sync_interval_minutes must be >= 1")
        s.sync_interval_minutes = body.sync_interval_minutes
    if body.active is not None:
        s.active = body.active
    if body.zip_code is not None:
        candidate = body.zip_code.strip()
        if candidate and not re.fullmatch(r"\d{5}(-\d{4})?", candidate):
            raise HTTPException(status_code=400, detail="zip_code must be a 5-digit (or ZIP+4) US zip code")
        s.zip_code = candidate or None
    if body.timezone is not None:
        candidate = body.timezone.strip()
        if candidate:
            try:
                ZoneInfo(candidate)
            except Exception:
                raise HTTPException(status_code=400, detail=f"'{candidate}' is not a recognized IANA timezone (e.g. America/Los_Angeles)")
        s.timezone = candidate or None
    db.commit()
    db.refresh(s)
    return _station_out(db, s)


@router.post("/admin/stations/{station_id}/rotate-credential", response_model=StationCredentialOut)
def rotate_station_credential(station_id: int, db: Session = Depends(get_db)):
    """Issue a fresh device_secret (e.g. suspected leak). Old credential stops
    working immediately — the station's local sync config must be updated
    with the new secret before it can push again."""
    s = db.query(Station).filter(Station.id == station_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Station not found")
    device_secret = gen_device_secret()
    s.device_secret_hash = hash_secret(device_secret)
    db.commit()
    return StationCredentialOut(station_id=s.id, device_id=s.device_id, device_secret=device_secret)


# ── Users ─────────────────────────────────────────────────────────────────────

def _user_out(db: Session, u: User) -> UserOut:
    cust = db.query(Customer).filter(Customer.id == u.customer_id).first() if u.customer_id else None
    assigned = db.execute(
        text("SELECT station_id FROM user_station_assignments WHERE user_id = :uid"), {"uid": u.id}
    ).fetchall()
    return UserOut(
        id=u.id, email=u.email, role=u.role, customer_id=u.customer_id,
        customer_name=cust.name if cust else None, active=u.active, created_at=u.created_at,
        assigned_station_ids=[r[0] for r in assigned],
    )


@router.get("/admin/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.email).all()
    return [_user_out(db, u) for u in users]


@router.post("/admin/users", response_model=UserOut)
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    from auth import hash_secret as hash_password  # same bcrypt hasher, different name for clarity at call site
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    if body.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")
    u = User(
        email=body.email.lower(), password_hash=hash_password(body.password), role=body.role,
        customer_id=body.customer_id, active=True, created_at=datetime.now(tz=timezone.utc),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return _user_out(db, u)


@router.put("/admin/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db)):
    from auth import hash_secret as hash_password
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role is not None:
        if body.role not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    if body.customer_id is not None:
        u.customer_id = body.customer_id
    if body.password:
        u.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(u)
    return _user_out(db, u)


# ── Assignments ───────────────────────────────────────────────────────────────

@router.post("/admin/assignments")
def create_assignment(body: AssignmentCreate, db: Session = Depends(get_db)):
    if not db.query(User).filter(User.id == body.user_id).first():
        raise HTTPException(status_code=404, detail="User not found")
    if not db.query(Station).filter(Station.id == body.station_id).first():
        raise HTTPException(status_code=404, detail="Station not found")
    existing = db.query(UserStationAssignment).filter(
        UserStationAssignment.user_id == body.user_id, UserStationAssignment.station_id == body.station_id
    ).first()
    if existing:
        return {"ok": True, "already_assigned": True}
    db.add(UserStationAssignment(
        user_id=body.user_id, station_id=body.station_id, created_at=datetime.now(tz=timezone.utc),
    ))
    db.commit()
    return {"ok": True}


@router.delete("/admin/assignments")
def delete_assignment(user_id: int, station_id: int, db: Session = Depends(get_db)):
    row = db.query(UserStationAssignment).filter(
        UserStationAssignment.user_id == user_id, UserStationAssignment.station_id == station_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Sessions ──────────────────────────────────────────────────────────────────

@router.get("/admin/users/{user_id}/sessions", response_model=list[SessionOut])
def list_user_sessions(user_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id)
        .order_by(UserSession.created_at.desc())
        .all()
    )
    return [
        SessionOut(
            id=s.id, created_at=s.created_at, expires_at=s.expires_at, revoked_at=s.revoked_at,
            last_used_at=s.last_used_at, user_agent=s.user_agent, ip_address=s.ip_address,
        )
        for s in rows
    ]


@router.delete("/admin/sessions/{session_id}")
def revoke_session(session_id: int, db: Session = Depends(get_db)):
    s = db.query(UserSession).filter(UserSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    s.revoked_at = datetime.now(tz=timezone.utc)
    db.commit()
    return {"ok": True}


@router.delete("/admin/users/{user_id}/sessions")
def revoke_all_user_sessions(user_id: int, db: Session = Depends(get_db)):
    now = datetime.now(tz=timezone.utc)
    db.execute(
        text("UPDATE sessions SET revoked_at = :now WHERE user_id = :uid AND revoked_at IS NULL"),
        {"now": now, "uid": user_id},
    )
    db.commit()
    return {"ok": True}

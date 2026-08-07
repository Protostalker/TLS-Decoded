"""
Cloud API entry point — serves the Ingest API (station pushes) and the T1 +
T2 + T3 app API (all three tiers, one app, per CLOUD-ARCHITECTURE.md's data
flow diagram) from a single FastAPI process backed by the cloud DB.
"""
import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from auth import hash_secret
from database import Base, engine, get_db
from models import Customer, User
from routers import admin, auth_router, ingest, stations

app = FastAPI(
    title="TLS-Decoded Cloud API",
    description="Ingest API + T1/T2/T3 app API for the TLS-Decoded cloud hub",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    _bootstrap_admin()


def _migrate_schema() -> None:
    """create_all only creates missing tables, not missing columns on tables
    that already exist — idempotent ALTER TABLE ... ADD COLUMN IF NOT EXISTS
    here, same pattern the station stack's api/poller/sync containers use."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS zip_code TEXT"))
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS timezone TEXT"))
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS brand_preset TEXT"))
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS brand_primary_color TEXT"))
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS brand_secondary_color TEXT"))
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS brand_accent_color TEXT"))
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS brand_logo_data_url TEXT"))


def _bootstrap_admin() -> None:
    """
    First-run convenience: if ADMIN_EMAIL/ADMIN_PASSWORD are set and no admin
    user exists yet, create one — otherwise there's no way to log into T3 on
    a brand new cloud DB. No-op on every run after the first admin exists.
    """
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        return

    db = next(get_db())
    try:
        existing_admin = db.query(User).filter(User.role == "admin").first()
        if existing_admin:
            return

        customer = db.query(Customer).filter(Customer.name == "HTS Internal").first()
        if not customer:
            customer = Customer(name="HTS Internal", plan=None, created_at=datetime.now(tz=timezone.utc))
            db.add(customer)
            db.commit()
            db.refresh(customer)

        db.add(User(
            email=email.lower(), password_hash=hash_secret(password), role="admin",
            customer_id=customer.id, active=True, created_at=datetime.now(tz=timezone.utc),
        ))
        db.commit()
    finally:
        db.close()


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(ingest.router)                    # /ingest/* — device-credential auth
app.include_router(auth_router.router, prefix="/api")  # /api/auth/* — T2 login
app.include_router(stations.router, prefix="/api")     # /api/me/*, /api/stations/* — T1 + T2
app.include_router(admin.router, prefix="/api")        # /api/admin/* — T3


@app.get("/api/health")
def health(db=None):
    from database import SessionLocal
    ok = True
    try:
        s = SessionLocal()
        s.execute(text("SELECT 1"))
        s.close()
    except Exception:
        ok = False
    return {"status": "ok" if ok else "degraded", "db_ok": ok}

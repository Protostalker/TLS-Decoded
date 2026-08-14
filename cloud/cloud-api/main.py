"""
Cloud API entry point — serves the Ingest API (station pushes) and the T1 +
T2 + T3 app API (all three tiers, one app, per CLOUD-ARCHITECTURE.md's data
flow diagram) from a single FastAPI process backed by the cloud DB.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import licensing
from auth import hash_secret
from database import Base, engine, get_db
from models import Customer, FuelOrder, Notification, PushSubscription, User
from routers import admin, auth_router, ingest, license as license_router, notifications, push, stations, supplier

logger = logging.getLogger("cloud-api.main")

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
    licensing.run_license_check()  # evaluate once synchronously so the very first
                                    # request after boot already has a real status,
                                    # not "unconfigured" for up to an hour
    asyncio.create_task(_license_check_loop())


async def _license_check_loop():
    """Background phone-home loop — see licensing.py's module docstring.
    Interval is configurable (LICENSE_CHECK_INTERVAL_HOURS, default 24, per
    the dev handoff doc's 'recommend daily'); an Unlimited license still
    gets re-verified on this loop too (cheap, offline, and catches a
    misconfigured/corrupted license file promptly instead of only at the
    next restart)."""
    interval_hours = float(os.environ.get("LICENSE_CHECK_INTERVAL_HOURS", "24"))
    while True:
        await asyncio.sleep(max(interval_hours, 0.1) * 3600)
        try:
            licensing.run_license_check()
        except Exception:
            logger.exception("License check loop iteration failed — will retry next interval")


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
        # Supplier workflow tables — create_all handles new tables, but we add
        # explicit idempotent DDL here in case the DB was provisioned from an
        # older image that ran create_all before these models existed.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fuel_orders (
                id BIGSERIAL PRIMARY KEY,
                station_id INTEGER REFERENCES stations(id),
                supplier_user_id INTEGER REFERENCES users(id),
                ordered_at TIMESTAMPTZ NOT NULL,
                eta_note TEXT,
                snoozed_until TIMESTAMPTZ NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notifications (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                station_id INTEGER REFERENCES stations(id),
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                eta_note TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                read_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                subscription_json TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
        """))
        # Licensing — Cloud Utility only, see models.CloudLicenseState / licensing.py.
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS update_check_requested_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS update_check_acked_at TIMESTAMPTZ"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cloud_license_state (
                id INTEGER PRIMARY KEY,
                license_type TEXT,
                customer_name TEXT,
                station_scope TEXT,
                status TEXT NOT NULL DEFAULT 'unconfigured',
                activated_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ,
                last_check_at TIMESTAMPTZ,
                last_check_ok BOOLEAN,
                last_check_detail TEXT,
                failing_since TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("ALTER TABLE cloud_license_state ADD COLUMN IF NOT EXISTS configured_type TEXT"))
        conn.execute(text("ALTER TABLE cloud_license_state ADD COLUMN IF NOT EXISTS configured_annual_key TEXT"))
        conn.execute(text("ALTER TABLE cloud_license_state ADD COLUMN IF NOT EXISTS configured_unlimited_file TEXT"))


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
app.include_router(ingest.router)                         # /ingest/* — device-credential auth
app.include_router(auth_router.router, prefix="/api")     # /api/auth/* — T2 login
app.include_router(stations.router, prefix="/api")        # /api/me/*, /api/stations/* — T1 + T2
app.include_router(admin.router, prefix="/api")           # /api/admin/* — T3
app.include_router(supplier.router, prefix="/api")        # /api/supplier/* — supplier dashboard
app.include_router(notifications.router, prefix="/api")   # /api/notifications/*
app.include_router(push.router, prefix="/api")            # /api/push/*
app.include_router(license_router.router, prefix="/api")  # /api/license/* — banner (any user), status/recheck (admin)


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

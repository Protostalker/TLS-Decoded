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
from routers import admin, auth_router, driver, fleet, ingest, license as license_router, notifications, push, stations, supplier

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
        # Map pin — see models.py's Station.address/lat/lng.
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS address TEXT"))
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION"))
        conn.execute(text("ALTER TABLE stations ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION"))
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
        # Delivery timer fields (distance/route-estimate phase) — see
        # models.py's FuelOrder docstring. All nullable/additive.
        conn.execute(text("ALTER TABLE fuel_orders ADD COLUMN IF NOT EXISTS origin_label TEXT"))
        conn.execute(text("ALTER TABLE fuel_orders ADD COLUMN IF NOT EXISTS origin_lat DOUBLE PRECISION"))
        conn.execute(text("ALTER TABLE fuel_orders ADD COLUMN IF NOT EXISTS origin_lng DOUBLE PRECISION"))
        conn.execute(text("ALTER TABLE fuel_orders ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE fuel_orders ADD COLUMN IF NOT EXISTS eta_minutes DOUBLE PRECISION"))
        conn.execute(text("ALTER TABLE fuel_orders ADD COLUMN IF NOT EXISTS route_distance_km DOUBLE PRECISION"))

        # Fleet: loading racks, tankers, daisy-chain delivery runs (Phase 3).
        # create_all handles these for a fresh DB; explicit DDL here covers
        # an existing DB from before these models existed, same pattern as
        # the supplier workflow tables above.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS loading_racks (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id),
                name TEXT NOT NULL,
                address TEXT, lat DOUBLE PRECISION, lng DOUBLE PRECISION,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tankers (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id),
                label TEXT NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tanker_compartments (
                id SERIAL PRIMARY KEY,
                tanker_id INTEGER NOT NULL REFERENCES tankers(id),
                label TEXT NOT NULL,
                capacity_gallons DOUBLE PRECISION NOT NULL,
                display_order INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tanker_loads (
                id BIGSERIAL PRIMARY KEY,
                tanker_id INTEGER NOT NULL REFERENCES tankers(id),
                loading_rack_id INTEGER NOT NULL REFERENCES loading_racks(id),
                created_by_user_id INTEGER NOT NULL REFERENCES users(id),
                loaded_at TIMESTAMPTZ NOT NULL,
                note TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tanker_load_items (
                id BIGSERIAL PRIMARY KEY,
                tanker_load_id BIGINT NOT NULL REFERENCES tanker_loads(id),
                tanker_compartment_id INTEGER NOT NULL REFERENCES tanker_compartments(id),
                product TEXT NOT NULL,
                gallons DOUBLE PRECISION NOT NULL,
                gallons_remaining DOUBLE PRECISION NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS delivery_runs (
                id BIGSERIAL PRIMARY KEY,
                tanker_load_id BIGINT NOT NULL REFERENCES tanker_loads(id),
                supplier_user_id INTEGER NOT NULL REFERENCES users(id),
                status TEXT NOT NULL DEFAULT 'planned',
                created_at TIMESTAMPTZ NOT NULL,
                dispatched_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ
            )
        """))
        # Driver account phase — see models.DeliveryRun/MagicLink.
        conn.execute(text("ALTER TABLE delivery_runs ADD COLUMN IF NOT EXISTS driver_user_id INTEGER REFERENCES users(id)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS magic_links (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                token_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                used_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS delivery_stops (
                id BIGSERIAL PRIMARY KEY,
                delivery_run_id BIGINT NOT NULL REFERENCES delivery_runs(id),
                station_id INTEGER NOT NULL REFERENCES stations(id),
                stop_order INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                started_at TIMESTAMPTZ,
                eta_minutes DOUBLE PRECISION,
                distance_km DOUBLE PRECISION,
                arrived_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS delivery_stop_items (
                id BIGSERIAL PRIMARY KEY,
                delivery_stop_id BIGINT NOT NULL REFERENCES delivery_stops(id),
                tanker_load_item_id BIGINT NOT NULL REFERENCES tanker_load_items(id),
                product TEXT NOT NULL,
                gallons_planned DOUBLE PRECISION NOT NULL,
                gallons_delivered DOUBLE PRECISION
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
        # Remote tank-config / grade correction (cloud -> station), built on
        # the same queue+pull pattern as pending_price_updates. create_all
        # makes the table for a fresh DB; this keeps an older-image DB in sync.
        conn.execute(text("ALTER TABLE cloud_tanks ADD COLUMN IF NOT EXISTS display_order INTEGER"))
        conn.execute(text("ALTER TABLE cloud_tanks ADD COLUMN IF NOT EXISTS name_override TEXT"))
        conn.execute(text("ALTER TABLE cloud_tanks ADD COLUMN IF NOT EXISTS product_override TEXT"))
        conn.execute(text("ALTER TABLE cloud_tanks ADD COLUMN IF NOT EXISTS display_order_override INTEGER"))
        conn.execute(text("ALTER TABLE cloud_tanks ADD COLUMN IF NOT EXISTS override_note TEXT"))
        conn.execute(text("ALTER TABLE cloud_tanks ADD COLUMN IF NOT EXISTS override_set_at TIMESTAMPTZ"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pending_tank_updates (
                id SERIAL PRIMARY KEY,
                station_id INTEGER REFERENCES stations(id) NOT NULL,
                tank_local_id INTEGER NOT NULL,
                set_name BOOLEAN NOT NULL DEFAULT FALSE,
                name TEXT,
                set_product BOOLEAN NOT NULL DEFAULT FALSE,
                product TEXT,
                set_active BOOLEAN NOT NULL DEFAULT FALSE,
                active BOOLEAN,
                set_display_order BOOLEAN NOT NULL DEFAULT FALSE,
                display_order INTEGER,
                note TEXT,
                created_by_user_id INTEGER REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL,
                applied_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cloud_license_state (
                id INTEGER PRIMARY KEY,
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
        conn.execute(text("ALTER TABLE cloud_license_state ADD COLUMN IF NOT EXISTS configured_passphrase TEXT"))
        conn.execute(text("ALTER TABLE cloud_license_state ADD COLUMN IF NOT EXISTS instance_id TEXT"))
        # Columns from an earlier (JWT/signing-key based) design, now unused
        # — left in place rather than dropped (harmless orphan columns,
        # avoids a DROP COLUMN migration for something with no ORM mapping
        # anymore anyway). Safe to manually drop later if you want a clean
        # schema: license_type, configured_type, configured_annual_key,
        # configured_unlimited_file.


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
app.include_router(fleet.router, prefix="/api")           # /api/fleet/* — racks/tankers/loads/delivery runs
app.include_router(driver.router, prefix="/api")          # /api/driver/* — a driver's own assigned runs
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

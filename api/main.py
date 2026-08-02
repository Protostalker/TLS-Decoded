"""FastAPI application entry point."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import yaml
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import Reading, Tank
from routers import deliveries, export, health, insights, pricing, readings, settings, tanks
from schemas import DashboardOut, PredictionOut, ReadingOut, TankOut
from routers.readings import _calc_rate

app = FastAPI(
    title="TLS-Decoded API",
    description="Veeder-Root TLS-350 monitoring — Gardena Sinclair",
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
    # Columns added after initial deployment — kept in sync with the same
    # migration the poller runs, so either service can bring the schema
    # up to date regardless of container start order.
    migrations = [
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS adjusted_gallons_received REAL",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS confirmed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS manual_gallons_received REAL",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS manually_confirmed_at TIMESTAMPTZ",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS merged_poll_count INTEGER DEFAULT 1",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS session_started_at TIMESTAMPTZ",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS note TEXT",
    ]
    with engine.begin() as conn:
        for m in migrations:
            conn.execute(text(m))


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router, prefix="/api")
app.include_router(tanks.router, prefix="/api")
app.include_router(readings.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(deliveries.router, prefix="/api")
app.include_router(pricing.router, prefix="/api")


# ── Dashboard ─────────────────────────────────────────────────────────────────

def _load_station_name() -> str:
    try:
        cfg_path = os.environ.get("CONFIG_PATH", "/app/config/tls-decoded.yaml")
        with open(cfg_path) as f:
            raw = yaml.safe_load(f)
        return raw.get("station", {}).get("name", "Fuel Station")
    except Exception:
        return "Fuel Station"


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)):
    station_name = _load_station_name()

    active_tanks = db.query(Tank).filter(Tank.active == True).order_by(Tank.id).all()
    tank_outs: list[TankOut] = []
    predictions: list[PredictionOut] = []

    for tank in active_tanks:
        latest = (
            db.query(Reading)
            .filter(Reading.tank_id == tank.id)
            .order_by(Reading.polled_at.desc())
            .first()
        )
        tank_out = TankOut.model_validate(tank)
        tank_out.latest_reading = ReadingOut.model_validate(latest) if latest else None
        tank_outs.append(tank_out)

        current_volume = latest.volume_gallons if latest and latest.volume_gallons else 0.0

        rate_rows = db.execute(
            text(
                """
                SELECT polled_at, volume_gallons FROM readings
                WHERE tank_id = :tid
                  AND polled_at >= NOW() - INTERVAL '168 hours'
                  AND volume_gallons IS NOT NULL
                ORDER BY polled_at ASC
                """
            ),
            {"tid": tank.id},
        ).fetchall()

        rate = _calc_rate(rate_rows)

        age_hours = db.execute(
            text(
                "SELECT EXTRACT(EPOCH FROM (MAX(polled_at) - MIN(polled_at))) / 3600.0 "
                "FROM readings WHERE tank_id = :tid"
            ),
            {"tid": tank.id},
        ).scalar()
        data_hours = float(age_hours) if age_hours else 0.0
        confidence = "low" if data_hours < 48 else ("medium" if data_hours < 168 else "high")

        if rate and rate > 0:
            rate_per_day = rate * 24.0
            reorder_threshold = tank.reorder_threshold_gallons or 0.0
            now = datetime.now(tz=timezone.utc)

            days_until_reorder = None
            projected_reorder_date = None
            if current_volume > reorder_threshold:
                days_until_reorder = (current_volume - reorder_threshold) / rate_per_day
                projected_reorder_date = (now + timedelta(days=days_until_reorder)).isoformat()

            days_until_empty = current_volume / rate_per_day if rate_per_day > 0 else None

            predictions.append(PredictionOut(
                tank_id=tank.id,
                consumption_rate_gal_per_hour=round(rate, 4),
                consumption_rate_gal_per_day=round(rate_per_day, 2),
                days_until_reorder=round(days_until_reorder, 2) if days_until_reorder is not None else None,
                days_until_empty=round(days_until_empty, 2) if days_until_empty is not None else None,
                projected_reorder_date=projected_reorder_date,
                confidence=confidence,
            ))
        else:
            predictions.append(PredictionOut(
                tank_id=tank.id,
                consumption_rate_gal_per_hour=None,
                consumption_rate_gal_per_day=None,
                days_until_reorder=None,
                days_until_empty=None,
                projected_reorder_date=None,
                confidence="low",
                note="Insufficient data",
            ))

    last_poll: Optional[datetime] = None
    try:
        last_poll = db.execute(
            text("SELECT polled_at FROM poll_log ORDER BY polled_at DESC LIMIT 1")
        ).scalar()
    except Exception:
        pass

    return DashboardOut(
        station_name=station_name,
        tanks=tank_outs,
        predictions=predictions,
        last_poll_at=last_poll,
    )

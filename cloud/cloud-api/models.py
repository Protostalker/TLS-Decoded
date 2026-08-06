"""
Cloud DB ORM models.

Two families of tables:

1. Tenancy / auth — customers, stations, users, assignments, sessions. These
   are new; there's no local-station equivalent.

2. Mirrored station data — cloud_tanks, cloud_readings, cloud_delivery_events,
   cloud_fuel_prices, cloud_poll_log. Same shape as the local per-station
   tables (see ../../api/models.py), each with a station_id column added for
   tenant scoping, plus a `local_id` column carrying the row's id (or, for
   tanks, the station-local tank id) from the station's own database. The
   pair (station_id, local_id) is the idempotency key the sync service's
   pushes upsert against — safe to retry a batch after a network blip
   without creating duplicates.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Float, ForeignKey, Integer, Numeric, Text, TIMESTAMP,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# ── Tenancy / auth ───────────────────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str | None] = mapped_column(Text)  # free-text for now; billing is a later concern
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))

    stations: Mapped[list["Station"]] = relationship("Station", back_populates="customer")
    users: Mapped[list["User"]] = relationship("User", back_populates="customer")


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("customers.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # Station device credential (machine-to-machine, issued by an admin in T3
    # when the station is provisioned). device_id is public-ish (sent on every
    # push); device_secret is only ever shown once at provisioning time and
    # stored here as a hash — same posture as user passwords.
    device_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    device_secret_hash: Mapped[str] = mapped_column(Text, nullable=False)

    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    # US zip code — optional, set by an admin from T3. Powers the weather
    # panel/recommendations on T1/T2 (see weather.py); nothing else depends
    # on it, so it's safe to leave blank.
    zip_code: Mapped[str | None] = mapped_column(Text)

    # IANA tz name (e.g. "America/Los_Angeles") — set by an admin from T3.
    # Calendar-day boundaries ("today consumed", day-by-day margin) are
    # computed in THIS timezone, matching how the station's own local
    # dashboard defines "today" (see api/routers/insights.py's STATION_TZ).
    # Falls back to America/Los_Angeles if unset — matches this codebase's
    # only station so far; set explicitly for any station in another tz.
    timezone: Mapped[str | None] = mapped_column(Text)

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))

    customer: Mapped["Customer"] = relationship("Customer", back_populates="stations")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="user")  # "admin" | "user"
    # Org grouping for display in T3 — visibility is still governed entirely
    # by user_station_assignments, not this field.
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))

    customer: Mapped["Customer | None"] = relationship("Customer", back_populates="users")


class UserStationAssignment(Base):
    __tablename__ = "user_station_assignments"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))


class PendingPriceUpdate(Base):
    """
    v1 sync is one-way (station -> cloud); this is a narrow, purpose-built
    exception so a price can be updated from the cloud side (T1) without a
    general remote-config channel. A user submits a price change here; the
    station's own `sync` container polls for pending rows (device-credential
    auth, same as ingest), applies them to the LOCAL fuel_prices table (the
    source of truth), then acks. The resulting local row flows back up to
    cloud_fuel_prices through the normal one-way push on the next cycle —
    this table is just the outbound queue, never a second source of truth.
    """
    __tablename__ = "pending_price_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), nullable=False)
    tank_local_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_per_gallon: Mapped[float | None] = mapped_column(Numeric(12, 6))
    tax_fees_per_gallon: Mapped[float | None] = mapped_column(Numeric(12, 6))
    tax_rate_percent: Mapped[float | None] = mapped_column(Numeric(9, 4))
    sale_price_per_gallon: Mapped[float | None] = mapped_column(Numeric(12, 6))
    effective_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class UserSession(Base):
    """DB-backed sessions (not JWT) — required because 'never expires' + admin
    revocation together rule out stateless tokens; see CLOUD-ARCHITECTURE.md."""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))  # NULL = never
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(Text)


# ── Mirrored per-station data ────────────────────────────────────────────────

class CloudTank(Base):
    __tablename__ = "cloud_tanks"
    __table_args__ = (UniqueConstraint("station_id", "local_id", name="uq_cloud_tanks_station_local"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), nullable=False)
    local_id: Mapped[int] = mapped_column(Integer, nullable=False)  # the tank's id in the station's own DB
    name: Mapped[str] = mapped_column(Text, nullable=False)
    product: Mapped[str | None] = mapped_column(Text)
    capacity_gallons: Mapped[float | None] = mapped_column(Float)
    reorder_threshold_gallons: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class CloudReading(Base):
    __tablename__ = "cloud_readings"
    __table_args__ = (UniqueConstraint("station_id", "local_id", name="uq_cloud_readings_station_local"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), nullable=False)
    local_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # readings.id on the station
    tank_local_id: Mapped[int] = mapped_column(Integer, nullable=False)
    polled_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    volume_gallons: Mapped[float | None] = mapped_column(Float)
    ullage_gallons: Mapped[float | None] = mapped_column(Float)
    height_inches: Mapped[float | None] = mapped_column(Float)
    water_inches: Mapped[float | None] = mapped_column(Float)
    temperature_f: Mapped[float | None] = mapped_column(Float)


class CloudDeliveryEvent(Base):
    __tablename__ = "cloud_delivery_events"
    __table_args__ = (UniqueConstraint("station_id", "local_id", name="uq_cloud_deliveries_station_local"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), nullable=False)
    local_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tank_local_id: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    start_volume_gallons: Mapped[float | None] = mapped_column(Float)
    end_volume_gallons: Mapped[float | None] = mapped_column(Float)
    gallons_received: Mapped[float | None] = mapped_column(Float)
    adjusted_gallons_received: Mapped[float | None] = mapped_column(Float)
    confirmed: Mapped[bool | None] = mapped_column(Boolean, default=False)
    manual_gallons_received: Mapped[float | None] = mapped_column(Float)
    manually_confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    merged_poll_count: Mapped[int | None] = mapped_column(Integer, default=1)
    session_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class CloudFuelPrice(Base):
    __tablename__ = "cloud_fuel_prices"
    __table_args__ = (UniqueConstraint("station_id", "local_id", name="uq_cloud_prices_station_local"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), nullable=False)
    local_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tank_local_id: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    cost_per_gallon: Mapped[float | None] = mapped_column(Numeric(12, 6))
    tax_fees_per_gallon: Mapped[float | None] = mapped_column(Numeric(12, 6), default=0)
    tax_rate_percent: Mapped[float | None] = mapped_column(Numeric(9, 4))
    sale_price_per_gallon: Mapped[float | None] = mapped_column(Numeric(12, 6))
    source: Mapped[str] = mapped_column(Text, default="manual")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class CloudPollLog(Base):
    __tablename__ = "cloud_poll_log"
    __table_args__ = (UniqueConstraint("station_id", "local_id", name="uq_cloud_polllog_station_local"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), nullable=False)
    local_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    polled_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    success: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

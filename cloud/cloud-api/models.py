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

    # Map pin (see routers/admin.py's geocode endpoint / routers/map.py).
    # address is free-text, shown as entered; lat/lng are what actually
    # places the pin. Either set directly (drag-the-pin) or derived by
    # geocoding `address` via Nominatim (OpenStreetMap, free, no API key) —
    # see geocoding.py. All optional; a station with no pin just doesn't
    # appear on the map, nothing else depends on this.
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)

    # IANA tz name (e.g. "America/Los_Angeles") — set by an admin from T3.
    # Calendar-day boundaries ("today consumed", day-by-day margin) are
    # computed in THIS timezone, matching how the station's own local
    # dashboard defines "today" (see api/routers/insights.py's STATION_TZ).
    # Falls back to America/Los_Angeles if unset — matches this codebase's
    # only station so far; set explicitly for any station in another tz.
    timezone: Mapped[str | None] = mapped_column(Text)

    # Cloud -> station "please check for updates now" flag — set by an admin
    # (routers/admin.py's request_update_check), cleared by the station's own
    # sync container once it's picked the request up and set the local
    # update_check_requested_at setting (see routers/ingest.py's
    # update_check_request endpoints + sync/main.py). Mirrors the
    # PendingPriceUpdate pattern: cloud never reaches into a station's
    # network, the station pulls on its own next tick instead.
    update_check_requested_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    update_check_acked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    # Branding — mirrored FROM the station (set locally, Settings ->
    # Branding), never edited from the cloud side. A customer with stations
    # under different fuel brands sees each one themed correctly: T1 for
    # this station uses these colors/logo; the T2 picker only uses them for
    # a small per-card accent, never for its own chrome. See
    # routers/ingest.py's station_info handling and sync/main.py's push.
    brand_preset: Mapped[str | None] = mapped_column(Text)
    brand_primary_color: Mapped[str | None] = mapped_column(Text)
    brand_secondary_color: Mapped[str | None] = mapped_column(Text)
    brand_accent_color: Mapped[str | None] = mapped_column(Text)
    brand_logo_data_url: Mapped[str | None] = mapped_column(Text)

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))

    customer: Mapped["Customer"] = relationship("Customer", back_populates="stations")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="user")  # "admin" | "user" | "supplier"
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


class PendingTankUpdate(Base):
    """
    The second narrow exception to "v1 sync is one-way (station -> cloud)",
    built on exactly the same rails as PendingPriceUpdate: a tank's config
    (its grade/product label, display name, active flag, or display order)
    can be corrected from the cloud side (T1 Grades panel, admin only)
    without a general remote-config channel and without the cloud ever
    reaching into a station's network.

    Why this exists: a station whose grades are mislabeled/misordered in the
    field normally gets fixed on the local client, but when there's no local
    or network access to that box, there was no way to correct it. This row
    is the outbound queue for that correction. The station's own `sync`
    container polls for pending rows (device-credential auth, same as
    ingest), applies them to the LOCAL tanks table (the source of truth),
    then acks. The resulting local row flows back up to cloud_tanks through
    the normal one-way push next cycle — this table is never a second source
    of truth, just a queue.

    Each field is paired with a set_* flag rather than relying on NULL, so
    "clear the product to NULL" is distinguishable from "don't touch the
    product" — the same distinction the local TankUpdate schema draws with
    model_fields_set, preserved across the queue.
    """
    __tablename__ = "pending_tank_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), nullable=False)
    tank_local_id: Mapped[int] = mapped_column(Integer, nullable=False)

    set_name: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    name: Mapped[str | None] = mapped_column(Text)
    set_product: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    product: Mapped[str | None] = mapped_column(Text)
    set_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool | None] = mapped_column(Boolean)
    set_display_order: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int | None] = mapped_column(Integer)

    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class MagicLink(Base):
    """
    A passwordless login link, generated on demand by an admin (or a
    supplier, for their own drivers) and shared manually — text, email,
    whatever — since SMTP sending isn't wired up yet. Redeeming one (POST
    /api/auth/magic-login) creates a normal session exactly like a
    password login would (see auth.py's create_session), so once a driver
    taps the link they're logged in the regular way from then on; the link
    itself is only consumed once (used_at set) and expires on its own
    after a while even if never used.

    One active (unused, unexpired) link per user is the intended usage —
    generating a new one for the same user doesn't delete old rows, but
    the admin UI only ever shows/links the most recent, so in practice an
    old unused link is simply never shared and quietly expires.
    """
    __tablename__ = "magic_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


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
    # Display/sort order for this station's tanks on T1 (and the local
    # dashboard). NULL sorts last, then by local_id, so a station that has
    # never had an explicit order set still renders in a stable, sensible
    # sequence. Set from the cloud Grades panel (admin) -> queued as a
    # PendingTankUpdate -> applied locally by the station's sync container
    # -> mirrored back here through the normal one-way push, same path as
    # any other tank edit.
    display_order: Mapped[int | None] = mapped_column(Integer)
    # Cloud-ONLY display overrides (temporary). Set from the admin Grades
    # panel when a grade is mislabeled on the station but the correction
    # can't be pushed down yet (or you want the supplier to see the right
    # label immediately). NEVER written by ingest (see routers/ingest.py —
    # the tank upsert does not list these columns), so a station push can't
    # clobber them; they live purely in the cloud mirror and render in red
    # with an asterisk + note until the real station-side name catches up,
    # at which point an admin clears the override.
    name_override: Mapped[str | None] = mapped_column(Text)
    product_override: Mapped[str | None] = mapped_column(Text)
    # Cloud-only order override — wins over display_order for sorting in the
    # cloud view (COALESCE), so tanks can be reordered for the supplier
    # without touching the station. Also never written by ingest.
    display_order_override: Mapped[int | None] = mapped_column(Integer)
    override_note: Mapped[str | None] = mapped_column(Text)
    override_set_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
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


# ── Supplier workflow ────────────────────────────────────────────────────────

class FuelOrder(Base):
    """
    Records a supplier's 'I have ordered fuel' action for a station.
    snoozed_until = ordered_at + 6h; while active the station sinks to the
    bottom of the supplier's urgency-sorted list with a countdown badge.
    Designed to be the foundation for a real ordering integration in a later
    phase (e.g. linking to a fuel supplier's PO system) — don't add a
    'completed' column yet; that's phase 2.

    origin_* / dispatched_at / eta_minutes / route_distance_km (added in the
    distance/delivery-timer phase) are ALL optional — a supplier who just
    types a free-text ETA note, like before, leaves these null and gets no
    timer badge. They're only populated when the supplier also gives a
    pickup location, which routing.route() turns into a one-time distance/
    duration estimate at order time. No GPS, no live tracking — just
    elapsed-time-vs-estimate math (see routers/supplier.py).
    """
    __tablename__ = "fuel_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), nullable=False)
    supplier_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    ordered_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    eta_note: Mapped[str | None] = mapped_column(Text)
    snoozed_until: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    origin_label: Mapped[str | None] = mapped_column(Text)
    origin_lat: Mapped[float | None] = mapped_column(Float)
    origin_lng: Mapped[float | None] = mapped_column(Float)
    dispatched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    eta_minutes: Mapped[float | None] = mapped_column(Float)
    route_distance_km: Mapped[float | None] = mapped_column(Float)


# ── Fleet: loading racks, tankers, and daisy-chain delivery runs ───────────
# (Phase 3 of the Fuel Provider feature list.)

class LoadingRack(Base):
    """
    A place a tanker can load fuel from (a terminal/depot/rack) — the
    origin end of a delivery. Owned by a customer (the fuel provider's own
    company), same tenancy pattern as Station. Address/lat/lng mirror
    Station's map-pin fields exactly (geocoded via geocoding.py), so a rack
    shows up on the same map as its own marker.
    """
    __tablename__ = "loading_racks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class Tanker(Base):
    """
    A physical delivery vehicle. Its compartments (TankerCompartment) are a
    property of the TANKER — defined once and reused across many loads,
    "per tank, not per delivery," per the original ask. What a compartment
    is actually carrying on a given trip is recorded separately, per load
    (TankerLoadItem), so the same 2x10k-gallon tanker can run all-diesel one
    day and a diesel/unleaded split the next without redefining its
    physical layout each time.
    """
    __tablename__ = "tankers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id"))
    label: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "Tanker 7"
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class TankerCompartment(Base):
    """One physical compartment on a tanker — fixed capacity, reused across loads."""
    __tablename__ = "tanker_compartments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tanker_id: Mapped[int] = mapped_column(Integer, ForeignKey("tankers.id"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "Tank 1"
    capacity_gallons: Mapped[float] = mapped_column(Float, nullable=False)
    display_order: Mapped[int | None] = mapped_column(Integer)


class TankerLoad(Base):
    """
    One loading event: this tanker picked up fuel at this rack. What each
    compartment was actually loaded with (which product(s), how many
    gallons) lives in TankerLoadItem, entered once here via the %/max UI
    (routers/fleet.py), then drawn down across however many delivery stops
    make up the daisy chain (DeliveryStopItem) — loading and delivering are
    deliberately separate steps, matching how the feature was described.
    """
    __tablename__ = "tanker_loads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tanker_id: Mapped[int] = mapped_column(Integer, ForeignKey("tankers.id"), nullable=False)
    loading_rack_id: Mapped[int] = mapped_column(Integer, ForeignKey("loading_racks.id"), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class TankerLoadItem(Base):
    """
    One product/gallons line within one compartment of one load — e.g.
    "compartment 1: 3500 gal diesel". Multiple rows can share a compartment
    (the %-split case, e.g. 35% diesel + 65% unleaded in the same
    compartment) — see routers/fleet.py's create_load for the
    percent-to-gallons math and the "max" button's semantics.
    """
    __tablename__ = "tanker_load_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tanker_load_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tanker_loads.id"), nullable=False)
    tanker_compartment_id: Mapped[int] = mapped_column(Integer, ForeignKey("tanker_compartments.id"), nullable=False)
    product: Mapped[str] = mapped_column(Text, nullable=False)
    gallons: Mapped[float] = mapped_column(Float, nullable=False)
    # How much of THIS line is still unallocated to any delivery stop —
    # starts equal to gallons, decremented as DeliveryStopItems are created
    # against it. Denormalized (not SUM-recomputed on every read) so a
    # partially-allocated load's remaining capacity is a cheap read on the
    # fleet dashboard; kept in lockstep inside the same transaction that
    # creates a DeliveryStopItem — see routers/fleet.py.
    gallons_remaining: Mapped[float] = mapped_column(Float, nullable=False)


class DeliveryRun(Base):
    """
    A daisy-chain delivery: one TankerLoad, dropped off across one or more
    stations in sequence (DeliveryStop, ordered by stop_order). status
    moves planned -> dispatched -> completed (or cancelled). dispatched_at
    is when the truck left the loading rack — the clock start for stop 1's
    leg timer (see delivery.py; later stops start their own leg timer when
    the stop before them is marked arrived).

    driver_user_id (added in the Driver-account phase) is optional — a run
    created without one just doesn't show up on anyone's Driver dashboard;
    the supplier/admin fleet views work exactly as before either way.
    """
    __tablename__ = "delivery_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tanker_load_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tanker_loads.id"), nullable=False)
    supplier_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    driver_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="planned")  # planned|dispatched|completed|cancelled
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class DeliveryStop(Base):
    """
    One stop in a DeliveryRun's daisy chain. started_at/eta_minutes/
    distance_km describe THIS LEG ONLY (previous stop, or the rack for
    stop_order 0, -> this station) — see routing.route() for how they're
    computed and delivery.py for how they turn into a progress bar.
    started_at is set when the truck leaves the previous point (the run's
    dispatch, for the first stop; the prior stop's arrived_at, for every
    stop after that) — never inherited from the run's own dispatched_at
    past stop 0, so each later leg gets its own fresh timer.
    """
    __tablename__ = "delivery_stops"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    delivery_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("delivery_runs.id"), nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id"), nullable=False)
    stop_order: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based position in the chain
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")  # pending|in_transit|delivered
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    eta_minutes: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    arrived_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class DeliveryStopItem(Base):
    """One product/gallons line being dropped at one stop, drawn from the
    run's TankerLoad (see TankerLoadItem.gallons_remaining)."""
    __tablename__ = "delivery_stop_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    delivery_stop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("delivery_stops.id"), nullable=False)
    tanker_load_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tanker_load_items.id"), nullable=False)
    product: Mapped[str] = mapped_column(Text, nullable=False)
    gallons_planned: Mapped[float] = mapped_column(Float, nullable=False)
    gallons_delivered: Mapped[float | None] = mapped_column(Float)


class Notification(Base):
    """
    In-app notification for admin/user-role recipients. Currently only type
    'fuel_ordered' is created; the type column lets future features (e.g. low
    tank alarm, delivery confirmed) fan into the same bell-icon UI without a
    schema change.
    """
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    station_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stations.id"))
    type: Mapped[str] = mapped_column(Text, nullable=False)   # "fuel_ordered" | ...
    message: Mapped[str] = mapped_column(Text, nullable=False)
    eta_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class PushSubscription(Base):
    """
    Browser Web Push subscription (serialised PushSubscription JSON from the
    browser's PushManager.subscribe() call). One user may have many — one per
    browser/device they've approved. Upserted on the endpoint so re-loading
    the same browser doesn't create duplicates.
    """
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    subscription_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


# ── Licensing (Cloud Utility only — Local Instance never touches this) ──────

class CloudLicenseState(Base):
    """
    Single-row table (id is always 1) holding this Cloud Utility's current
    license state — cached locally so the app can answer "am I licensed?"
    instantly on every request without a network round-trip per check, and
    so degraded mode survives a restart while the license server happens to
    be unreachable. See ../licensing.py for how this gets populated.

    Deliberately simple, per Raffi's call: one passphrase, always phoned
    home, no offline verification, no signing keys, no license files.

    configured_passphrase is stored as entered (plaintext in this table) —
    same as cloud_sync_device_secret in the station's own settings table:
    it's a credential this service must re-present as-is on every
    phone-home call, not a password being verified against a hash.
    """
    __tablename__ = "cloud_license_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # What's actually CONFIGURED — set either by CLOUD_LICENSE_KEY at first
    # boot (initial-deployment convenience only) or, from then on, by an
    # admin via Admin -> License in the cloud frontend (routers/license.py's
    # activate/deactivate). Once set via the UI, env vars are never
    # consulted again — see licensing.py's _seed_from_env_once().
    configured_passphrase: Mapped[str | None] = mapped_column(Text)

    # Generated once, the first time this Cloud Utility ever activates a
    # license, and never changed again — sent on every phone-home so the
    # license server can tell "this same instance checking in again" apart
    # from "a different instance trying to activate with the same code"
    # (see license-server/models.py's LicenseRedemption). Persists across
    # deactivating/reactivating with a different code on purpose — the
    # SAME instance, new license.
    instance_id: Mapped[str | None] = mapped_column(Text)

    # What the last check returned.
    customer_name: Mapped[str | None] = mapped_column(Text)
    station_scope: Mapped[str | None] = mapped_column(Text)

    # "active" | "grace" | "degraded" | "unconfigured" — see licensing.py's
    # run_license_check() for the state machine. "grace" means "currently
    # failing but within the 45-day window," matching the dev handoff doc's
    # "unreachable or invalid for 45 consecutive days -> degraded" language.
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unconfigured")

    activated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))  # from the license server; NULL for the master/unlimited code

    last_check_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_check_detail: Mapped[str | None] = mapped_column(Text)

    # First moment the *current* streak of failures (unreachable or invalid)
    # began — cleared back to NULL the moment a check succeeds. status
    # flips to "degraded" once (now - failing_since) >= LICENSE_GRACE_DAYS.
    failing_since: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

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

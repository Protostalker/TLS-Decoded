"""
TLS-Decoded Poller — entry point.

Lifecycle:
  1. Load config
  2. Connect to DB, ensure schema exists
  3. Sync tank config from YAML → tanks table
  4. Run one immediate poll
  5. Schedule subsequent polls per config (interval or schedule mode)
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import sqlalchemy
from sqlalchemy import text

from analytics import compute_consumption_rate, detect_delivery
from commander_prices import check_commander_heartbeat, sync_commander_prices
from config import AppConfig, TankConfig, load_config
from mock_driver import MockDriver
from models import DeliveryEvent, PollResult, TankReading
from network_driver import TLSNetworkDriver
from uploader import RemoteUploader

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("poller.main")

DB_URL = os.environ.get("DATABASE_URL", "")


# ── Database helpers ──────────────────────────────────────────────────────────

def wait_for_db(engine: sqlalchemy.Engine, retries: int = 30) -> None:
    for i in range(retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection established")
            return
        except Exception as exc:
            logger.warning("DB not ready (%s), retrying in 3s… (%d/%d)", exc, i + 1, retries)
            time.sleep(3)
    raise RuntimeError("Could not connect to database after retries")


def ensure_schema(engine: sqlalchemy.Engine) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS tanks (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        product TEXT,
        capacity_gallons REAL,
        reorder_threshold_gallons REAL,
        active BOOLEAN DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS fuel_prices (
        id BIGSERIAL PRIMARY KEY,
        tank_id INTEGER REFERENCES tanks(id),
        effective_at TIMESTAMPTZ NOT NULL,
        cost_per_gallon NUMERIC(12,6),
        tax_fees_per_gallon NUMERIC(12,6) DEFAULT 0,
        tax_rate_percent NUMERIC(9,4),
        sale_price_per_gallon NUMERIC(12,6),
        source TEXT DEFAULT 'manual',
        note TEXT,
        created_at TIMESTAMPTZ
    );

    CREATE INDEX IF NOT EXISTS idx_fuel_prices_tank_time
        ON fuel_prices(tank_id, effective_at DESC);

    CREATE TABLE IF NOT EXISTS readings (
        id BIGSERIAL PRIMARY KEY,
        tank_id INTEGER REFERENCES tanks(id),
        polled_at TIMESTAMPTZ NOT NULL,
        volume_gallons REAL,
        ullage_gallons REAL,
        height_inches REAL,
        water_inches REAL,
        temperature_f REAL
    );

    CREATE INDEX IF NOT EXISTS idx_readings_tank_time
        ON readings(tank_id, polled_at DESC);

    CREATE TABLE IF NOT EXISTS delivery_events (
        id BIGSERIAL PRIMARY KEY,
        tank_id INTEGER REFERENCES tanks(id),
        detected_at TIMESTAMPTZ NOT NULL,
        start_volume_gallons REAL,
        end_volume_gallons REAL,
        gallons_received REAL
    );

    CREATE TABLE IF NOT EXISTS poll_log (
        id BIGSERIAL PRIMARY KEY,
        polled_at TIMESTAMPTZ NOT NULL,
        success BOOLEAN,
        error_message TEXT,
        duration_ms INTEGER
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))

    # Migrations for columns added after initial deployment (delivery_events
    # pre-dates adjusted_gallons_received/confirmed).
    migrations = [
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS adjusted_gallons_received REAL",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS confirmed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS manual_gallons_received REAL",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS manually_confirmed_at TIMESTAMPTZ",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS merged_poll_count INTEGER DEFAULT 1",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS session_started_at TIMESTAMPTZ",
        "ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS note TEXT",
        "ALTER TABLE fuel_prices ADD COLUMN IF NOT EXISTS tax_rate_percent NUMERIC(9,4)",
        "ALTER TABLE tanks ADD COLUMN IF NOT EXISTS commander_grade_id INTEGER",
    ]
    with engine.begin() as conn:
        for m in migrations:
            conn.execute(text(m))

    logger.info("Database schema ready")


# ── Settings (poll interval, alignment, device id, remote) ─────────────────────

def _gen_device_id() -> str:
    import secrets
    return secrets.token_hex(16)  # 32 hex chars


def seed_settings(engine: sqlalchemy.Engine, cfg: AppConfig) -> None:
    """Insert default settings from YAML the first time (never overwrites existing rows)."""
    defaults = {
        "poll_interval_minutes": str(cfg.polling.interval_minutes),
        "poll_aligned": "true",
        "device_id": cfg.remote.device_id or _gen_device_id(),
        "remote_enabled": "true" if cfg.remote.enabled else "false",
        "remote_server_url": cfg.remote.server_url or "",
        "poll_now_requested_at": "",
        # Commander price sync — env vars only seed this once, on first ever
        # boot (ON CONFLICT DO NOTHING below). After that the dashboard's
        # Settings -> Commander price sync toggle/fields are authoritative,
        # live-editable without a restart. A station with no Commander (or
        # an operator who won't allow the integration) just leaves this
        # disabled — pricing stays fully manual, same as before this existed.
        "commander_sync_enabled": "true" if os.environ.get("COMMANDER_READER_URL", "").strip() else "false",
        "commander_reader_url": os.environ.get("COMMANDER_READER_URL", "").strip(),
        "commander_price_tier": (os.environ.get("COMMANDER_PRICE_TIER") or "cash").strip().lower(),
        "commander_sync_interval_minutes": os.environ.get("COMMANDER_PRICE_SYNC_INTERVAL_MINUTES", "60"),
        "commander_last_check_at": "",
        "commander_last_connected": "",
        "commander_last_error": "",
        # Same seed-once-then-UI-wins pattern: DEFAULT_TAX_RATE_PERCENT env
        # var only sets the initial value; Settings -> Tax rate is
        # authoritative afterward, live, for both manual and Commander-synced
        # price entries.
        "default_tax_rate_percent": os.environ.get("DEFAULT_TAX_RATE_PERCENT", ""),
    }
    with engine.begin() as conn:
        for k, v in defaults.items():
            conn.execute(
                text(
                    "INSERT INTO settings (key, value) VALUES (:k, :v) "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {"k": k, "v": v},
            )
    logger.info("Settings seeded (idempotent)")


def get_settings(engine: sqlalchemy.Engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT key, value FROM settings")).fetchall()
    return {r.key: r.value for r in rows}


def clear_poll_now(engine: sqlalchemy.Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE settings SET value = '' WHERE key = 'poll_now_requested_at'")
        )


def current_aligned_slot(now: datetime, interval_minutes: int) -> datetime:
    """
    The most recent clock-aligned poll slot at or before `now`.
    e.g. interval=30 -> slots at :00 and :30 every hour, anchored to midnight.
    """
    interval_minutes = max(1, interval_minutes)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_min = (now - midnight).total_seconds() / 60.0
    slot_index = int(elapsed_min // interval_minutes)
    return midnight + timedelta(minutes=slot_index * interval_minutes)


def sync_tanks(engine: sqlalchemy.Engine, tanks: list[TankConfig]) -> None:
    """
    Seed tank configs from YAML into the DB — but only for tanks that don't
    already exist there. Once a tank row exists, the DB is the source of
    truth for name/product/capacity/reorder-threshold (editable from the
    dashboard, e.g. to correct a tank size), and the poller will not stomp
    on those edits on every sync. Only `active` is always re-asserted.
    """
    with engine.begin() as conn:
        for t in tanks:
            conn.execute(
                text(
                    """
                    INSERT INTO tanks (id, name, product, capacity_gallons, reorder_threshold_gallons, active)
                    VALUES (:id, :name, :product, :cap, :reo, TRUE)
                    ON CONFLICT (id) DO UPDATE SET
                        active = TRUE
                    """
                ),
                {
                    "id": t.id,
                    "name": t.name,
                    "product": t.product,
                    "cap": t.capacity_gallons,
                    "reo": t.reorder_threshold_gallons,
                },
            )
    logger.info("Tank configs synced to DB (%d tanks; existing rows left untouched)", len(tanks))


def get_last_readings(engine: sqlalchemy.Engine) -> dict[int, TankReading]:
    """Fetch the most recent reading per tank (for delivery detection)."""
    sql = text(
        """
        SELECT DISTINCT ON (tank_id)
            tank_id, polled_at, volume_gallons, ullage_gallons,
            height_inches, water_inches, temperature_f
        FROM readings
        ORDER BY tank_id, polled_at DESC
        """
    )
    result: dict[int, TankReading] = {}
    with engine.connect() as conn:
        for row in conn.execute(sql):
            result[row.tank_id] = TankReading(
                tank_id=row.tank_id,
                polled_at=row.polled_at,
                volume_gallons=row.volume_gallons,
                ullage_gallons=row.ullage_gallons,
                height_inches=row.height_inches,
                water_inches=row.water_inches,
                temperature_f=row.temperature_f,
            )
    return result


# ── Persistence ───────────────────────────────────────────────────────────────

def persist_readings(engine: sqlalchemy.Engine, readings: list[TankReading]) -> None:
    with engine.begin() as conn:
        for r in readings:
            conn.execute(
                text(
                    """
                    INSERT INTO readings (
                        tank_id, polled_at, volume_gallons, ullage_gallons,
                        height_inches, water_inches, temperature_f
                    ) VALUES (
                        :tank_id, :polled_at, :vol, :ullage, :height, :water, :temp
                    )
                    """
                ),
                {
                    "tank_id": r.tank_id,
                    "polled_at": r.polled_at,
                    "vol": r.volume_gallons,
                    "ullage": r.ullage_gallons,
                    "height": r.height_inches,
                    "water": r.water_inches,
                    "temp": r.temperature_f,
                },
            )


def persist_delivery(engine: sqlalchemy.Engine, event: DeliveryEvent) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO delivery_events (
                    tank_id, detected_at, start_volume_gallons, end_volume_gallons,
                    gallons_received, adjusted_gallons_received, confirmed,
                    session_started_at, merged_poll_count
                )
                VALUES (:tid, :det, :start, :end, :gal, :adj, :conf, :sess, :cnt)
                """
            ),
            {
                "tid": event.tank_id,
                "det": event.detected_at,
                "start": event.start_volume_gallons,
                "end": event.end_volume_gallons,
                "gal": event.gallons_received,
                "adj": event.adjusted_gallons_received,
                "conf": event.confirmed,
                "sess": event.session_started_at or event.detected_at,
                "cnt": event.merged_poll_count,
            },
        )


def find_mergeable_delivery(engine: sqlalchemy.Engine, tank_id: int, since: datetime):
    """
    Most recent delivery for this tank that's still "open" for merging: it was
    active recently and hasn't been manually confirmed/edited by an operator
    (once a human signs off on a number, the poller won't touch it again).
    """
    sql = text(
        """
        SELECT id, start_volume_gallons, end_volume_gallons, session_started_at, merged_poll_count
        FROM delivery_events
        WHERE tank_id = :tid AND detected_at >= :since AND manual_gallons_received IS NULL
        ORDER BY detected_at DESC
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        return conn.execute(sql, {"tid": tank_id, "since": since}).first()


def merge_delivery(
    engine: sqlalchemy.Engine,
    delivery_id: int,
    end_volume_gallons: float,
    detected_at: datetime,
    gallons_received: float,
    adjusted_gallons_received: float,
    merged_poll_count: int,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE delivery_events
                SET end_volume_gallons = :end_vol,
                    detected_at = :det,
                    gallons_received = :gal,
                    adjusted_gallons_received = :adj,
                    merged_poll_count = :cnt,
                    confirmed = TRUE
                WHERE id = :id
                """
            ),
            {
                "end_vol": end_volume_gallons,
                "det": detected_at,
                "gal": gallons_received,
                "adj": adjusted_gallons_received,
                "cnt": merged_poll_count,
                "id": delivery_id,
            },
        )


def persist_poll_log(engine: sqlalchemy.Engine, result: PollResult) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO poll_log (polled_at, success, error_message, duration_ms)
                VALUES (:at, :ok, :err, :dur)
                """
            ),
            {
                "at": result.polled_at,
                "ok": result.success,
                "err": result.error_message,
                "dur": result.duration_ms,
            },
        )


# ── Poll cycle ────────────────────────────────────────────────────────────────

class Poller:
    def __init__(self, cfg: AppConfig, engine: sqlalchemy.Engine):
        self._cfg = cfg
        self._engine = engine
        self._uploader = RemoteUploader(cfg.remote)

        if cfg.network.mock:
            logger.info("Using MOCK driver (network.mock=true)")
            self._driver = MockDriver(cfg)
        else:
            logger.info(
                "Using NETWORK driver → %s:%d", cfg.network.host, cfg.network.port
            )
            self._driver = TLSNetworkDriver(cfg.network)

    # A discrete delivery (tanker drop) commonly takes 10-20+ minutes. Catching
    # it with a single follow-up poll risks measuring it mid-drop — understating
    # the total if fuel is also being sold at the pumps during that window.
    # These re-polls let the volume settle before we lock in the numbers.
    DELIVERY_CONFIRM_ROUNDS = 3
    DELIVERY_CONFIRM_GAP_SECONDS = 120

    def _confirm_deliveries(self, provisional: list[DeliveryEvent]) -> list[DeliveryEvent]:
        pending = {e.tank_id: e for e in provisional}
        best: dict[int, tuple[float, datetime]] = {
            tid: (e.end_volume_gallons, e.detected_at) for tid, e in pending.items()
        }

        for round_i in range(self.DELIVERY_CONFIRM_ROUNDS):
            time.sleep(self.DELIVERY_CONFIRM_GAP_SECONDS)
            try:
                confirm_readings = self._driver.poll_inventory(datetime.now(tz=timezone.utc))
            except Exception as exc:
                logger.warning("Delivery confirmation poll %d failed: %s", round_i + 1, exc)
                continue

            relevant = [r for r in confirm_readings if r.tank_id in pending]
            if relevant:
                persist_readings(self._engine, relevant)

            still_rising = False
            for r in relevant:
                if r.volume_gallons is None:
                    continue
                prev_vol, _ = best[r.tank_id]
                if r.volume_gallons > prev_vol:
                    best[r.tank_id] = (r.volume_gallons, r.polled_at)
                    still_rising = True
                elif r.volume_gallons == prev_vol:
                    best[r.tank_id] = (r.volume_gallons, r.polled_at)

            if not still_rising:
                break  # volume has settled (or started falling again) — done early

        finalized: list[DeliveryEvent] = []
        for tid, event in pending.items():
            end_vol, end_time = best[tid]
            net_gallons = round(end_vol - event.start_volume_gallons, 1)

            # Estimate gallons that may have been sold concurrently during the
            # confirmation window, using the tank's rolling consumption rate,
            # and add that back for a "gross" estimate of what was delivered.
            rate = compute_consumption_rate(
                self._engine, tid, self._cfg.analytics.consumption_window_hours
            ) or 0.0
            elapsed_hours = max(0.0, (end_time - event.detected_at).total_seconds() / 3600.0)
            estimated_concurrent_sold = rate * elapsed_hours
            adjusted = round(net_gallons + estimated_concurrent_sold, 1)

            finalized.append(DeliveryEvent(
                tank_id=tid,
                detected_at=end_time,
                start_volume_gallons=event.start_volume_gallons,
                end_volume_gallons=end_vol,
                gallons_received=net_gallons,
                adjusted_gallons_received=adjusted,
                confirmed=True,
                session_started_at=event.detected_at,  # original pre-confirmation jump time
                merged_poll_count=1,
            ))
        return finalized

    # If the tank's most recent open (not manually confirmed) delivery session
    # was still active this recently, a new jump is treated as a continuation
    # of the same fill-up rather than a brand new delivery. Some deliveries at
    # this station run up to ~2 hours, so this needs to cover that fully.
    MERGE_WINDOW_MINUTES = 120
    # Allow a little normal consumption between polls before deciding a new
    # jump doesn't actually connect to the prior session's end volume.
    MERGE_CONTIGUITY_TOLERANCE_GALLONS = 150

    def _merge_or_persist_delivery(self, event: DeliveryEvent) -> None:
        since = datetime.now(tz=timezone.utc) - timedelta(minutes=self.MERGE_WINDOW_MINUTES)
        prior = find_mergeable_delivery(self._engine, event.tank_id, since)

        if prior and event.start_volume_gallons >= (prior.end_volume_gallons or 0) - self.MERGE_CONTIGUITY_TOLERANCE_GALLONS:
            session_start = prior.session_started_at or event.session_started_at or event.detected_at
            merged_net = round(event.end_volume_gallons - prior.start_volume_gallons, 1)

            rate = compute_consumption_rate(
                self._engine, event.tank_id, self._cfg.analytics.consumption_window_hours
            ) or 0.0
            elapsed_hours = max(0.0, (event.detected_at - session_start).total_seconds() / 3600.0)
            merged_adjusted = round(merged_net + rate * elapsed_hours, 1)
            merged_count = (prior.merged_poll_count or 1) + 1

            merge_delivery(
                self._engine, prior.id,
                end_volume_gallons=event.end_volume_gallons,
                detected_at=event.detected_at,
                gallons_received=merged_net,
                adjusted_gallons_received=merged_adjusted,
                merged_poll_count=merged_count,
            )
            logger.info(
                "Merged delivery into session #%d for tank %d: total +%.0f gal across %d polls",
                prior.id, event.tank_id, merged_net, merged_count,
            )
        else:
            persist_delivery(self._engine, event)
            self._uploader.upload_delivery(event)
            logger.info(
                "Delivery event saved: tank %d net +%.0f gal (adjusted est. +%.0f gal, confirmed=%s)",
                event.tank_id,
                event.gallons_received,
                event.adjusted_gallons_received or event.gallons_received,
                event.confirmed,
            )

    def run_poll(self) -> None:
        start = time.monotonic()
        polled_at = datetime.now(tz=timezone.utc)
        logger.info("--- Poll starting at %s ---", polled_at.isoformat())

        error_msg = None
        success = False
        readings: list[TankReading] = []

        try:
            # ── Inventory ──
            readings = self._driver.poll_inventory(polled_at)
            if not readings:
                raise RuntimeError("No readings returned by driver")

            # ── Delivery detection ──
            prev_readings = get_last_readings(self._engine)
            deliveries: list[DeliveryEvent] = []
            for r in readings:
                event = detect_delivery(
                    prev_readings.get(r.tank_id),
                    r,
                    self._cfg.analytics.delivery_detection_jump_gallons,
                )
                if event:
                    deliveries.append(event)

            # ── Persist readings ──
            persist_readings(self._engine, readings)
            logger.info("Saved %d readings", len(readings))

            # ── Confirm deliveries (a delivery may still be running, or fuel
            #    could be being dispensed at the same time — a single poll
            #    reading right after the jump can under/overstate the true
            #    amount received) ──
            if deliveries:
                deliveries = self._confirm_deliveries(deliveries)

            # ── Persist deliveries (merging into an in-progress session when
            #    this is a continuation of a jump seen in a recent prior poll) ──
            for event in deliveries:
                self._merge_or_persist_delivery(event)

            # ── Remote upload ──
            self._uploader.upload_readings(readings)

            success = True

        except Exception as exc:
            error_msg = str(exc)
            logger.error("Poll failed: %s", exc, exc_info=True)

        duration_ms = int((time.monotonic() - start) * 1000)
        persist_poll_log(
            self._engine,
            PollResult(
                polled_at=polled_at,
                success=success,
                duration_ms=duration_ms,
                readings=readings,
                error_message=error_msg,
            ),
        )
        logger.info("--- Poll done (%dms, success=%s) ---", duration_ms, success)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("TLS-Decoded Poller starting…")

    cfg = load_config()
    logger.info("Config loaded — station: %s, %d tanks", cfg.station_name, len(cfg.tanks))

    engine = sqlalchemy.create_engine(DB_URL, pool_pre_ping=True)
    wait_for_db(engine)
    ensure_schema(engine)
    sync_tanks(engine, cfg.tanks)
    seed_settings(engine, cfg)

    poller = Poller(cfg, engine)

    # ── First poll immediately ──
    poller.run_poll()

    # Commander price sync (opt-in, no-op unless enabled in Settings) also
    # runs once at startup, then on its own interval below — fully decoupled
    # from the TLS poll cadence above. Heartbeat (cheap /health-only check)
    # runs separately and much more often so Settings -> Commander price
    # sync shows current status within minutes, not up to an hour stale.
    startup_settings = get_settings(engine)
    sync_commander_prices(engine, startup_settings)
    check_commander_heartbeat(engine, startup_settings)

    now = datetime.now(tz=timezone.utc)
    last_poll_at = now
    last_slot_polled = current_aligned_slot(now, cfg.polling.interval_minutes)
    last_commander_sync_at = now
    last_commander_heartbeat_at = now

    logger.info(
        "Entering scheduling loop — poll interval/alignment are now controlled "
        "live from the `settings` table (editable from the dashboard)."
    )

    # ── Live, settings-driven scheduling loop ──────────────────────────────────
    # Poll interval + clock-alignment are re-read from the DB every tick, so
    # changes made from the frontend take effect within TICK_SECONDS without
    # restarting the poller. A "poll now" request (also set via the frontend)
    # is honored immediately.
    TICK_SECONDS = 15
    while True:
        try:
            settings = get_settings(engine)
        except Exception as exc:
            logger.warning("Could not read settings (%s), using last known config", exc)
            settings = {}

        interval_minutes = int(settings.get("poll_interval_minutes") or cfg.polling.interval_minutes)
        aligned = (settings.get("poll_aligned") or "true").lower() == "true"
        poll_now_requested = bool(settings.get("poll_now_requested_at"))

        now = datetime.now(tz=timezone.utc)
        should_poll = False

        if poll_now_requested:
            should_poll = True
            try:
                clear_poll_now(engine)
            except Exception:
                pass
        elif aligned:
            slot = current_aligned_slot(now, interval_minutes)
            if slot != last_slot_polled and now >= slot:
                should_poll = True
                last_slot_polled = slot
        else:
            if now - last_poll_at >= timedelta(minutes=interval_minutes):
                should_poll = True

        if should_poll:
            poller.run_poll()
            last_poll_at = datetime.now(tz=timezone.utc)
            last_slot_polled = current_aligned_slot(last_poll_at, interval_minutes)

        commander_sync_interval = int(
            settings.get("commander_sync_interval_minutes")
            or os.environ.get("COMMANDER_PRICE_SYNC_INTERVAL_MINUTES", "60")
        )
        if now - last_commander_sync_at >= timedelta(minutes=commander_sync_interval):
            sync_commander_prices(engine, settings)
            last_commander_sync_at = now

        # Heartbeat: cheap, frequent — independent of the full sync above so
        # "last checked" in Settings -> Commander price sync stays within a
        # few minutes of reality instead of up to an hour stale.
        commander_heartbeat_interval = int(os.environ.get("COMMANDER_HEARTBEAT_INTERVAL_MINUTES", "5"))
        if now - last_commander_heartbeat_at >= timedelta(minutes=commander_heartbeat_interval):
            check_commander_heartbeat(engine, settings)
            last_commander_heartbeat_at = now

        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    main()

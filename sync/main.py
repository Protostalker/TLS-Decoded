"""
TLS-Decoded Sync — pushes this station's data to the cloud hub on a timer.

Own container, same reasoning as keeping API and poller separate (see
CLOUD-ARCHITECTURE.md): a hung outbound push shouldn't affect on-site
polling. Only ever dials out — never listens for anything, never needs a
known address, and the station stack works exactly as it does today with
this container stopped or removed entirely.

Lifecycle:
  1. Load config (env vars — see config.py — these only SEED the settings
     table the first time the container ever starts; see seed_cloud_sync_settings)
  2. Connect to the LOCAL station DB, ensure sync-support schema exists
     (updated_at columns + triggers on the tables that get edited after
     first write, plus the sync_checkpoint table)
  3. Loop forever: every tick, re-read cloud_sync_enabled/url/credentials/
     interval from the `settings` table (editable live from the dashboard,
     same pattern the poller uses for poll_interval_minutes — no restart to
     turn sync on/off or repoint it); if enabled and due, push everything
     since the last checkpoint, table by table, retrying with backoff on
     failure, then record cloud_sync_last_synced_at on success.

Nothing here is ever deleted or trimmed from the local DB — if the cloud is
unreachable, the checkpoint just doesn't advance, and the next tick (or the
one after that, or after that) picks up right where it left off.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import sqlalchemy
from sqlalchemy import text

from config import SyncConfig, load_config

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync.main")

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ── Database setup ────────────────────────────────────────────────────────────

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


def ensure_sync_schema(engine: sqlalchemy.Engine) -> None:
    """
    Idempotent migration against the LOCAL station DB — same pattern the api
    and poller containers already use for their own incremental ALTER TABLE
    ADD COLUMN IF NOT EXISTS migrations against this shared database. Adds:

      - updated_at columns (+ a trigger to auto-touch them) on the three
        tables that get edited after their first write: tanks (capacity
        corrections), delivery_events (merges/confirmations), fuel_prices
        (edits). Readings and poll_log are append-only at the source, so
        they don't need this — an id high-water-mark is sufficient there.
      - sync_checkpoint: one row per synced table, tracking how far the
        last successful push got.
    """
    ddl = """
    CREATE OR REPLACE FUNCTION sync_touch_updated_at() RETURNS trigger AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))

    for table in ("tanks", "delivery_events", "fuel_prices"):
        with engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now()"
            ))
            # Backfill existing rows so nothing is stuck at NULL forever —
            # they'll be picked up on the very next sync cycle instead of
            # waiting for an actual future edit.
            conn.execute(text(f"UPDATE {table} SET updated_at = now() WHERE updated_at IS NULL"))
            conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}"))
            conn.execute(text(
                f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION sync_touch_updated_at()"
            ))

    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS sync_checkpoint (
                table_name TEXT PRIMARY KEY,
                last_id BIGINT NOT NULL DEFAULT 0,
                last_updated_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01T00:00:00Z',
                last_updated_id BIGINT NOT NULL DEFAULT 0
            )
            """
        ))
        for table in ("readings", "poll_log", "tanks", "delivery_events", "fuel_prices"):
            conn.execute(
                text("INSERT INTO sync_checkpoint (table_name) VALUES (:t) ON CONFLICT DO NOTHING"),
                {"t": table},
            )

    logger.info("Sync-support schema ready (updated_at columns/triggers + sync_checkpoint)")


# ── Settings (shared KV table also used by api/poller) ──────────────────────
#
# cloud_sync_* keys are surfaced and editable from the local dashboard's
# Settings panel (via the local api — see api/routers/settings.py), same
# live-without-restart pattern the poller uses for poll_interval_minutes.
# Env vars (config.py) only seed these once, the first time the container
# ever starts; after that the DB is the source of truth.

CLOUD_SYNC_KEYS = (
    "cloud_sync_enabled", "cloud_sync_url", "cloud_sync_device_id",
    "cloud_sync_device_secret", "cloud_sync_interval_minutes",
)

# Branding is station-owned config, not telemetry — pushed alongside the
# regular batch below (best-effort, never blocks/fails the sync cycle) so
# the cloud's mirrored copy of "what this station looks like" stays in sync
# with whatever was last saved in the local dashboard's Settings panel. See
# api/routers/settings.py for where these keys get written locally.
BRAND_KEYS = (
    "brand_preset", "brand_primary_color", "brand_secondary_color",
    "brand_accent_color", "brand_logo_data_url",
)


def get_branding_settings(engine: sqlalchemy.Engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT key, value FROM settings WHERE key = ANY(:keys)"),
            {"keys": list(BRAND_KEYS)},
        ).fetchall()
    v = {r.key: r.value for r in rows}
    return {
        "brand_preset": v.get("brand_preset") or None,
        "brand_primary_color": v.get("brand_primary_color") or None,
        "brand_secondary_color": v.get("brand_secondary_color") or None,
        "brand_accent_color": v.get("brand_accent_color") or None,
        "brand_logo_data_url": v.get("brand_logo_data_url") or None,
    }


def get_setting(engine: sqlalchemy.Engine, key: str) -> Optional[str]:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": key}).first()
    return row[0] if row else None


def set_setting(engine: sqlalchemy.Engine, key: str, value: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO settings (key, value) VALUES (:k, :v) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"k": key, "v": value},
        )


def seed_cloud_sync_settings(engine: sqlalchemy.Engine, cfg) -> None:
    """Insert cloud_sync_* defaults from env the first time only — never
    overwrites a value already present, exactly like poller's seed_settings.
    Auto-enables if all three connection fields were provided via env
    (the docker-compose.yml / .env path); otherwise starts disabled and
    waits for someone to fill it in from the dashboard."""
    auto_enable = bool(cfg.seed_cloud_url and cfg.seed_device_id and cfg.seed_device_secret)
    defaults = {
        "cloud_sync_enabled": "true" if auto_enable else "false",
        "cloud_sync_url": cfg.seed_cloud_url,
        "cloud_sync_device_id": cfg.seed_device_id,
        "cloud_sync_device_secret": cfg.seed_device_secret,
        "cloud_sync_interval_minutes": str(cfg.seed_interval_minutes),
    }
    with engine.begin() as conn:
        for k, v in defaults.items():
            conn.execute(
                text("INSERT INTO settings (key, value) VALUES (:k, :v) ON CONFLICT (key) DO NOTHING"),
                {"k": k, "v": v},
            )
    logger.info("Cloud sync settings seeded (idempotent, auto_enable=%s)", auto_enable)


def get_cloud_sync_settings(engine: sqlalchemy.Engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT key, value FROM settings WHERE key = ANY(:keys)"),
            {"keys": list(CLOUD_SYNC_KEYS)},
        ).fetchall()
    v = {r.key: (r.value or "") for r in rows}
    try:
        interval = int(v.get("cloud_sync_interval_minutes") or 30)
    except ValueError:
        interval = 30
    return {
        "enabled": (v.get("cloud_sync_enabled") or "false").lower() == "true",
        "url": (v.get("cloud_sync_url") or "").rstrip("/"),
        "device_id": v.get("cloud_sync_device_id") or "",
        "device_secret": v.get("cloud_sync_device_secret") or "",
        "interval_minutes": interval,
    }


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def get_checkpoint(engine: sqlalchemy.Engine, table: str) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT last_id, last_updated_at, last_updated_id FROM sync_checkpoint WHERE table_name = :t"),
            {"t": table},
        ).first()
    if not row:
        return {"last_id": 0, "last_updated_at": EPOCH, "last_updated_id": 0}
    return {"last_id": row[0], "last_updated_at": row[1], "last_updated_id": row[2]}


def advance_checkpoint_by_id(engine: sqlalchemy.Engine, table: str, last_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE sync_checkpoint SET last_id = :v WHERE table_name = :t AND :v > last_id"),
            {"v": last_id, "t": table},
        )


def advance_checkpoint_by_updated(engine: sqlalchemy.Engine, table: str, last_updated_at, last_updated_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE sync_checkpoint SET last_updated_at = :ts, last_updated_id = :id "
                "WHERE table_name = :t"
            ),
            {"ts": last_updated_at, "id": last_updated_id, "t": table},
        )


# ── Fetch batches from the local DB ──────────────────────────────────────────

def fetch_readings(engine: sqlalchemy.Engine, since_id: int, limit: int) -> list[dict]:
    sql = text(
        """
        SELECT id, tank_id, polled_at, volume_gallons, ullage_gallons,
               height_inches, water_inches, temperature_f
        FROM readings WHERE id > :since ORDER BY id ASC LIMIT :limit
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"since": since_id, "limit": limit}).mappings().all()
    return [
        {
            "local_id": r["id"], "tank_local_id": r["tank_id"], "polled_at": r["polled_at"].isoformat(),
            "volume_gallons": r["volume_gallons"], "ullage_gallons": r["ullage_gallons"],
            "height_inches": r["height_inches"], "water_inches": r["water_inches"],
            "temperature_f": r["temperature_f"],
        }
        for r in rows
    ]


def fetch_poll_log(engine: sqlalchemy.Engine, since_id: int, limit: int) -> list[dict]:
    sql = text(
        "SELECT id, polled_at, success, error_message, duration_ms "
        "FROM poll_log WHERE id > :since ORDER BY id ASC LIMIT :limit"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"since": since_id, "limit": limit}).mappings().all()
    return [
        {
            "local_id": r["id"], "polled_at": r["polled_at"].isoformat(), "success": r["success"],
            "error_message": r["error_message"], "duration_ms": r["duration_ms"],
        }
        for r in rows
    ]


def fetch_tanks(engine: sqlalchemy.Engine, since_ts, since_id: int, limit: int) -> list[dict]:
    sql = text(
        """
        SELECT id, name, product, capacity_gallons, reorder_threshold_gallons, active, updated_at
        FROM tanks WHERE (updated_at, id) > (:since_ts, :since_id)
        ORDER BY updated_at ASC, id ASC LIMIT :limit
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"since_ts": since_ts, "since_id": since_id, "limit": limit}).mappings().all()
    return [
        {
            "local_id": r["id"], "name": r["name"], "product": r["product"],
            "capacity_gallons": r["capacity_gallons"], "reorder_threshold_gallons": r["reorder_threshold_gallons"],
            "active": r["active"], "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


def fetch_delivery_events(engine: sqlalchemy.Engine, since_ts, since_id: int, limit: int) -> list[dict]:
    sql = text(
        """
        SELECT id, tank_id, detected_at, start_volume_gallons, end_volume_gallons,
               gallons_received, adjusted_gallons_received, confirmed, manual_gallons_received,
               manually_confirmed_at, merged_poll_count, session_started_at, note, updated_at
        FROM delivery_events WHERE (updated_at, id) > (:since_ts, :since_id)
        ORDER BY updated_at ASC, id ASC LIMIT :limit
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"since_ts": since_ts, "since_id": since_id, "limit": limit}).mappings().all()
    out = []
    for r in rows:
        out.append({
            "local_id": r["id"], "tank_local_id": r["tank_id"], "detected_at": r["detected_at"].isoformat(),
            "start_volume_gallons": r["start_volume_gallons"], "end_volume_gallons": r["end_volume_gallons"],
            "gallons_received": r["gallons_received"], "adjusted_gallons_received": r["adjusted_gallons_received"],
            "confirmed": r["confirmed"], "manual_gallons_received": r["manual_gallons_received"],
            "manually_confirmed_at": r["manually_confirmed_at"].isoformat() if r["manually_confirmed_at"] else None,
            "merged_poll_count": r["merged_poll_count"],
            "session_started_at": r["session_started_at"].isoformat() if r["session_started_at"] else None,
            "note": r["note"], "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        })
    return out


def fetch_fuel_prices(engine: sqlalchemy.Engine, since_ts, since_id: int, limit: int) -> list[dict]:
    sql = text(
        """
        SELECT id, tank_id, effective_at, cost_per_gallon, tax_fees_per_gallon, tax_rate_percent,
               sale_price_per_gallon, source, note, created_at, updated_at
        FROM fuel_prices WHERE (updated_at, id) > (:since_ts, :since_id)
        ORDER BY updated_at ASC, id ASC LIMIT :limit
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"since_ts": since_ts, "since_id": since_id, "limit": limit}).mappings().all()
    out = []
    for r in rows:
        out.append({
            "local_id": r["id"], "tank_local_id": r["tank_id"], "effective_at": r["effective_at"].isoformat(),
            "cost_per_gallon": float(r["cost_per_gallon"]) if r["cost_per_gallon"] is not None else None,
            "tax_fees_per_gallon": float(r["tax_fees_per_gallon"]) if r["tax_fees_per_gallon"] is not None else None,
            "tax_rate_percent": float(r["tax_rate_percent"]) if r["tax_rate_percent"] is not None else None,
            "sale_price_per_gallon": float(r["sale_price_per_gallon"]) if r["sale_price_per_gallon"] is not None else None,
            "source": r["source"], "note": r["note"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        })
    return out


# ── Push ──────────────────────────────────────────────────────────────────────

class PushError(Exception):
    pass


def push_batch(client: httpx.Client, cloud_url: str, headers: dict, batch: dict) -> dict:
    resp = client.post(f"{cloud_url}/ingest/batch", headers=headers, json=batch)
    if resp.status_code >= 400:
        raise PushError(f"{resp.status_code}: {resp.text[:300]}")
    return resp.json()


def push_with_retry(client: httpx.Client, cloud_url: str, headers: dict, batch: dict, max_attempts: int = 5) -> Optional[dict]:
    delay = 5.0
    for attempt in range(1, max_attempts + 1):
        try:
            return push_batch(client, cloud_url, headers, batch)
        except (PushError, httpx.HTTPError) as exc:
            logger.warning("Push attempt %d/%d failed: %s", attempt, max_attempts, exc)
            if attempt == max_attempts:
                return None
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
    return None


# ── Price updates queued from the cloud side (T1) ────────────────────────────
#
# The one narrow exception to "v1 sync is one-way, station -> cloud only": a
# price entered on the cloud's T1 dashboard can't write to this station's DB
# directly, so it's queued cloud-side and picked up here every tick (not
# gated behind the push interval — an operator waiting on a price change
# shouldn't wait up to 30 minutes for it). Applying it locally makes
# fuel_prices the single source of truth either way — the resulting row
# flows back up to the cloud mirror through the normal push path next cycle,
# same as if someone had typed it in at the station itself.

def apply_pending_price_updates(engine: sqlalchemy.Engine, client: httpx.Client, cloud_url: str, headers: dict) -> int:
    try:
        resp = client.get(f"{cloud_url}/ingest/price-updates", headers=headers, timeout=15.0)
        resp.raise_for_status()
        updates = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not check for pending price updates: %s", exc)
        return 0

    applied = 0
    for u in updates:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO fuel_prices
                            (tank_id, effective_at, cost_per_gallon, tax_fees_per_gallon,
                             tax_rate_percent, sale_price_per_gallon, source, note, created_at)
                        VALUES
                            (:tank_id, :eff, :cost, :taxfee, :taxrate, :sale, 'cloud', :note, :created)
                        """
                    ),
                    {
                        "tank_id": u["tank_local_id"], "eff": u["effective_at"],
                        "cost": u["cost_per_gallon"], "taxfee": u["tax_fees_per_gallon"],
                        "taxrate": u["tax_rate_percent"], "sale": u["sale_price_per_gallon"],
                        "note": u.get("note"), "created": datetime.now(tz=timezone.utc).isoformat(),
                    },
                )
            client.post(f"{cloud_url}/ingest/price-updates/{u['id']}/ack", headers=headers, timeout=15.0)
            applied += 1
            logger.info("Applied cloud-submitted price update for tank %s (update id %s)", u["tank_local_id"], u["id"])
        except Exception:
            logger.exception("Failed to apply price update id %s — will retry next tick (not acked)", u.get("id"))
    return applied


# ── One sync cycle ────────────────────────────────────────────────────────────

def run_sync_cycle(engine: sqlalchemy.Engine, client: httpx.Client, cloud_url: str, headers: dict, batch_size: int) -> bool:
    """Push everything pending, chunk by chunk, per table, until caught up or
    a push fails. Returns True if the station is fully caught up afterward."""
    any_failure = False

    # Append-only tables: track by id.
    for table, fetch_fn, batch_key in (
        ("readings", fetch_readings, "readings"),
        ("poll_log", fetch_poll_log, "poll_log"),
    ):
        for _ in range(20):  # bounded loop — 20 * batch_size rows per cycle, per table
            cp = get_checkpoint(engine, table)
            rows = fetch_fn(engine, cp["last_id"], batch_size)
            if not rows:
                break
            result = push_with_retry(client, cloud_url, headers, {batch_key: rows})
            if result is None:
                any_failure = True
                break
            advance_checkpoint_by_id(engine, table, rows[-1]["local_id"])
            logger.info("Synced %d %s (up to local id %d)", len(rows), table, rows[-1]["local_id"])
            if len(rows) < batch_size:
                break

    # Mutable tables: track by (updated_at, id).
    for table, fetch_fn, batch_key in (
        ("tanks", fetch_tanks, "tanks"),
        ("delivery_events", fetch_delivery_events, "delivery_events"),
        ("fuel_prices", fetch_fuel_prices, "fuel_prices"),
    ):
        for _ in range(20):
            cp = get_checkpoint(engine, table)
            rows = fetch_fn(engine, cp["last_updated_at"], cp["last_updated_id"], batch_size)
            if not rows:
                break
            result = push_with_retry(client, cloud_url, headers, {batch_key: rows})
            if result is None:
                any_failure = True
                break
            last = rows[-1]
            advance_checkpoint_by_updated(
                engine, table,
                datetime.fromisoformat(last["updated_at"]) if last.get("updated_at") else datetime.now(tz=timezone.utc),
                last["local_id"],
            )
            logger.info("Synced %d %s", len(rows), table)
            if len(rows) < batch_size:
                break

    # Branding — best-effort, no checkpoint (there's only ever one "current"
    # value per station, so every cycle just sends the latest). A failure
    # here is logged but never flips any_failure — losing a theme push for
    # one cycle isn't worth retrying the whole sync loop over, it'll just go
    # out again next cycle.
    try:
        branding = get_branding_settings(engine)
        if any(branding.values()):
            push_with_retry(client, cloud_url, headers, {"station_info": branding}, max_attempts=1)
    except Exception:
        logger.exception("Failed to push branding — will retry next cycle")

    return not any_failure


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("TLS-Decoded Sync starting…")
    cfg = load_config()

    engine = sqlalchemy.create_engine(cfg.database_url, pool_pre_ping=True)
    wait_for_db(engine)
    ensure_sync_schema(engine)
    seed_cloud_sync_settings(engine, cfg)

    client = httpx.Client(timeout=30.0)  # base_url/headers are per-cycle now — creds can change live

    last_sync_at: Optional[datetime] = None
    was_idle = True

    logger.info(
        "Entering sync loop — enabled/url/credentials/interval are all live-editable from the "
        "local dashboard's Settings panel (settings table, cloud_sync_* keys), same pattern the "
        "poller uses for poll interval. No restart needed to turn this on, off, or repoint it."
    )

    TICK_SECONDS = 15
    while True:
        try:
            cs = get_cloud_sync_settings(engine)
        except Exception:
            logger.exception("Could not read cloud_sync_* settings — will retry next tick")
            time.sleep(TICK_SECONDS)
            continue

        configured = bool(cs["enabled"] and cs["url"] and cs["device_id"] and cs["device_secret"])

        if not configured:
            if not was_idle:
                logger.info("Cloud sync disabled or not fully configured — idling.")
            was_idle = True
            time.sleep(TICK_SECONDS)
            continue

        if was_idle:
            logger.info("Cloud sync configured (%s) — resuming.", cs["url"])
            was_idle = False

        headers = {
            "X-Station-Device-Id": cs["device_id"],
            "X-Station-Device-Secret": cs["device_secret"],
            "Content-Type": "application/json",
        }

        # Checked every tick, independent of the push interval below — a
        # price update shouldn't have to wait up to 30 minutes.
        apply_pending_price_updates(engine, client, cs["url"], headers)

        now = datetime.now(tz=timezone.utc)
        due = last_sync_at is None or (now - last_sync_at) >= timedelta(minutes=cs["interval_minutes"])

        if due:
            logger.info("--- Sync cycle starting ---")
            try:
                caught_up = run_sync_cycle(engine, client, cs["url"], headers, cfg.batch_size)
                logger.info("--- Sync cycle done (fully caught up=%s) ---", caught_up)
                if caught_up:
                    set_setting(engine, "cloud_sync_last_synced_at", datetime.now(tz=timezone.utc).isoformat())
            except Exception:
                logger.exception("Sync cycle raised unexpectedly — will retry next cycle")
            last_sync_at = datetime.now(tz=timezone.utc)

        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    main()

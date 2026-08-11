"""
Hourly fuel price sync from commander-reader (a read-only REST proxy in
front of a Verifone Commander unit) into this station's fuel_prices table.

Opt-in and entirely separate from the TLS-350 polling cadence in main.py.
Config is read from the live `settings` table each cycle (commander_sync_enabled,
commander_reader_url, commander_price_tier), seeded once from the
COMMANDER_READER_URL / COMMANDER_PRICE_TIER env vars on first boot — after
that the dashboard's Settings -> Commander price sync panel is authoritative
and takes effect within a tick, no restart needed. A station whose site
doesn't run Commander, or whose operator won't allow the integration, just
leaves this disabled (or the URL blank) and keeps entering cost + sale price
manually via the dashboard, exactly as before this feature existed — nothing
else in the app depends on it.

── Why this only ever sets the sale price, never the cost ─────────────────
Commander controls what's live at the pump, i.e. the retail sale price. It
has no way to know what this station paid its fuel supplier — that number
only ever comes from an invoice, so cost_per_gallon stays a manual entry via
the dashboard. Each sync here carries the last known cost forward unchanged
and only updates sale_price_per_gallon (and recomputes tax off the current
cost using DEFAULT_TAX_RATE_PERCENT). If a tank has no price history at all
yet, sync is skipped for it until a first cost is entered manually — there's
nothing to carry forward.

── Why grade ids are an explicit per-tank allowlist ────────────────────────
Every station's Commander configuration is different: grade names repeat,
grade ids don't map to the same physical product across stations, and
unused/placeholder grade slots show up in the same response as real ones.
This only ever syncs a tank whose `commander_grade_id` has been explicitly
set (via the dashboard's tank editor), confirmed by whoever knows the
station — never "sync everything" or "match by name."
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
import sqlalchemy
from sqlalchemy import text

logger = logging.getLogger("poller.commander_prices")

_EPSILON = 1e-6


def _tax_dollars(cost: float, tax_rate_percent: Optional[float]) -> float:
    if tax_rate_percent is None:
        return 0.0
    return round(cost * float(tax_rate_percent) / 100, 6)


def _default_tax_rate_percent() -> Optional[float]:
    raw = os.environ.get("DEFAULT_TAX_RATE_PERCENT")
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("DEFAULT_TAX_RATE_PERCENT=%r is not a number — ignoring", raw)
        return None


def _tanks_with_grade_ids(engine: sqlalchemy.Engine) -> list[dict]:
    sql = text(
        "SELECT id, name, commander_grade_id FROM tanks "
        "WHERE active = TRUE AND commander_grade_id IS NOT NULL"
    )
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql)]


def _latest_price_row(engine: sqlalchemy.Engine, tank_id: int) -> Optional[dict]:
    sql = text(
        """
        SELECT cost_per_gallon, tax_rate_percent, sale_price_per_gallon
        FROM fuel_prices
        WHERE tank_id = :tid
        ORDER BY effective_at DESC
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"tid": tank_id}).first()
    return dict(row._mapping) if row else None


def _insert_price(
    engine: sqlalchemy.Engine,
    tank_id: int,
    cost: float,
    tax_rate_percent: Optional[float],
    sale: float,
    grade_id: int,
) -> None:
    now = datetime.now(tz=timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO fuel_prices (
                    tank_id, effective_at, cost_per_gallon, tax_rate_percent,
                    tax_fees_per_gallon, sale_price_per_gallon, source, note, created_at
                ) VALUES (
                    :tid, :at, :cost, :rate, :tax, :sale, 'commander_auto', :note, :created
                )
                """
            ),
            {
                "tid": tank_id,
                "at": now,
                "cost": cost,
                "rate": tax_rate_percent,
                "tax": _tax_dollars(cost, tax_rate_percent),
                "sale": sale,
                "note": f"Auto-synced from commander-reader (grade id {grade_id})",
                "created": now,
            },
        )


def _record_status(engine: sqlalchemy.Engine, connected: bool, error: Optional[str]) -> None:
    """Written after every attempt (success or failure) so Settings -> Commander
    price sync can show real, current status instead of the operator having
    to SSH in and run `curl http://<host>:8200/health` themselves."""
    now = datetime.now(tz=timezone.utc).isoformat()
    with engine.begin() as conn:
        for key, value in (
            ("commander_last_check_at", now),
            ("commander_last_connected", "true" if connected else "false"),
            ("commander_last_error", error or ""),
        ):
            conn.execute(
                text("INSERT INTO settings (key, value) VALUES (:k, :v) "
                     "ON CONFLICT (key) DO UPDATE SET value = :v"),
                {"k": key, "v": value},
            )


def sync_commander_prices(engine: sqlalchemy.Engine, settings: Optional[dict] = None) -> None:
    """Best-effort, single pass. Never raises — any failure is logged (and
    recorded to settings for the dashboard) and just retried on the next
    scheduled cycle (commander-reader already retries against the Commander
    itself, so no backoff needed here).

    `settings` is the same dict main.py's loop already re-fetches every tick
    for poll_interval_minutes/poll_aligned — reused here rather than a
    separate query, so the enabled toggle and URL take effect within a tick
    of being changed from Settings -> Commander price sync, no restart."""
    settings = settings or {}

    enabled = (settings.get("commander_sync_enabled") or "").lower() == "true"
    if not enabled:
        return  # feature off for this station — silent no-op either way

    base_url = (settings.get("commander_reader_url") or "").strip().rstrip("/")
    if not base_url:
        return  # enabled but never configured with a URL — nothing to do yet

    tier = (settings.get("commander_price_tier") or "cash").strip().lower()
    if tier not in ("cash", "credit"):
        logger.warning("commander_price_tier=%r not recognized, defaulting to 'cash'", tier)
        tier = "cash"

    try:
        tanks = _tanks_with_grade_ids(engine)

        with httpx.Client(timeout=10.0) as client:
            health = client.get(f"{base_url}/health")
            health.raise_for_status()
            if health.json().get("connected") is False:
                logger.warning("commander-reader reports Commander unreachable — skipping this cycle")
                _record_status(engine, connected=False, error="Commander unit unreachable (commander-reader is up, but connected=false)")
                return

            resp = client.get(f"{base_url}/prices")
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("stale"):
            logger.warning("commander-reader price cache is stale — skipping this cycle "
                            "rather than risk overwriting good data with unknown data")
            _record_status(engine, connected=True, error="Price cache is stale — skipped this cycle")
            return

        _record_status(engine, connected=True, error=None)

        if not tanks:
            logger.debug("No tanks have a commander_grade_id configured — nothing to sync")
            return

        grades_by_id = {g["id"]: g for g in payload.get("grades", [])}
        default_rate = _default_tax_rate_percent()

        for tank in tanks:
            tank_id, name, grade_id = tank["id"], tank["name"], tank["commander_grade_id"]
            grade = grades_by_id.get(grade_id)
            if grade is None:
                logger.warning(
                    "Tank %r (id %d) is mapped to Commander grade id %d, but that id wasn't "
                    "in this poll's /prices response — Commander config may have changed. Skipping.",
                    name, tank_id, grade_id,
                )
                continue

            in_effect = grade.get("in_effect") or {}
            new_sale = in_effect.get(tier)
            if new_sale is None:
                logger.warning(
                    "Tank %r: grade id %d has no in_effect.%s price this cycle — skipping.",
                    name, grade_id, tier,
                )
                continue
            new_sale = float(new_sale)

            prior = _latest_price_row(engine, tank_id)
            if prior is None or prior.get("cost_per_gallon") is None:
                logger.warning(
                    "Tank %r has no price history yet — enter an initial cost via the dashboard "
                    "before Commander sync can start (nothing to carry the cost forward from).",
                    name,
                )
                continue

            cost = float(prior["cost_per_gallon"])
            prior_sale = float(prior["sale_price_per_gallon"]) if prior.get("sale_price_per_gallon") is not None else None
            prior_rate = float(prior["tax_rate_percent"]) if prior.get("tax_rate_percent") is not None else None
            rate = default_rate if default_rate is not None else prior_rate

            unchanged = (
                prior_sale is not None and abs(prior_sale - new_sale) < _EPSILON
                and (prior_rate or 0) == (rate or 0)
            )
            if unchanged:
                continue

            _insert_price(engine, tank_id, cost, rate, new_sale, grade_id)
            logger.info(
                "Commander price sync: tank %r sale price now $%.4f/gal (grade id %d, cost carried "
                "forward at $%.4f/gal)",
                name, new_sale, grade_id, cost,
            )

    except Exception as exc:
        logger.warning("Commander price sync failed this cycle (%s) — will retry next cycle", exc)
        try:
            _record_status(engine, connected=False, error=str(exc))
        except Exception:
            pass  # don't let status recording itself break the poller loop

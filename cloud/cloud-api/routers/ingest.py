"""
Ingest API — the only endpoint stations ever talk to. Authenticated by device
credential (see auth.verify_device), never by a user session. Upserts pushed
rows into the mirrored cloud tables, keyed on (station_id, local_id) so a
retried batch after a dropped connection never creates duplicates.

Tanks / delivery_events / fuel_prices can be edited after their first push
(a delivery gets merged, a tank's capacity gets corrected, etc.), so those
are upserted with DO UPDATE. Readings and poll_log are append-only at the
source, so DO NOTHING is both correct and cheaper.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import verify_device
from database import get_db
from models import PendingPriceUpdate, Station
from schemas import IngestBatch, IngestResult

router = APIRouter()


@router.post("/ingest/batch", response_model=IngestResult)
def ingest_batch(
    batch: IngestBatch,
    db: Session = Depends(get_db),
    station: Station = Depends(verify_device),
):
    counts = {"tanks": 0, "readings": 0, "delivery_events": 0, "fuel_prices": 0, "poll_log": 0}

    for t in batch.tanks:
        db.execute(
            text(
                """
                INSERT INTO cloud_tanks
                    (station_id, local_id, name, product, capacity_gallons,
                     reorder_threshold_gallons, active, updated_at)
                VALUES
                    (:sid, :lid, :name, :product, :cap, :reo, :active, :upd)
                ON CONFLICT (station_id, local_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    product = EXCLUDED.product,
                    capacity_gallons = EXCLUDED.capacity_gallons,
                    reorder_threshold_gallons = EXCLUDED.reorder_threshold_gallons,
                    active = EXCLUDED.active,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "sid": station.id, "lid": t.local_id, "name": t.name, "product": t.product,
                "cap": t.capacity_gallons, "reo": t.reorder_threshold_gallons,
                "active": t.active, "upd": t.updated_at,
            },
        )
        counts["tanks"] += 1

    for r in batch.readings:
        db.execute(
            text(
                """
                INSERT INTO cloud_readings
                    (station_id, local_id, tank_local_id, polled_at, volume_gallons,
                     ullage_gallons, height_inches, water_inches, temperature_f)
                VALUES
                    (:sid, :lid, :tlid, :polled_at, :vol, :ullage, :height, :water, :temp)
                ON CONFLICT (station_id, local_id) DO NOTHING
                """
            ),
            {
                "sid": station.id, "lid": r.local_id, "tlid": r.tank_local_id,
                "polled_at": r.polled_at, "vol": r.volume_gallons, "ullage": r.ullage_gallons,
                "height": r.height_inches, "water": r.water_inches, "temp": r.temperature_f,
            },
        )
        counts["readings"] += 1

    for d in batch.delivery_events:
        db.execute(
            text(
                """
                INSERT INTO cloud_delivery_events
                    (station_id, local_id, tank_local_id, detected_at, start_volume_gallons,
                     end_volume_gallons, gallons_received, adjusted_gallons_received, confirmed,
                     manual_gallons_received, manually_confirmed_at, merged_poll_count,
                     session_started_at, note, updated_at)
                VALUES
                    (:sid, :lid, :tlid, :det, :start, :end, :gal, :adj, :conf,
                     :manual, :manconf, :cnt, :sess, :note, :upd)
                ON CONFLICT (station_id, local_id) DO UPDATE SET
                    detected_at = EXCLUDED.detected_at,
                    start_volume_gallons = EXCLUDED.start_volume_gallons,
                    end_volume_gallons = EXCLUDED.end_volume_gallons,
                    gallons_received = EXCLUDED.gallons_received,
                    adjusted_gallons_received = EXCLUDED.adjusted_gallons_received,
                    confirmed = EXCLUDED.confirmed,
                    manual_gallons_received = EXCLUDED.manual_gallons_received,
                    manually_confirmed_at = EXCLUDED.manually_confirmed_at,
                    merged_poll_count = EXCLUDED.merged_poll_count,
                    session_started_at = EXCLUDED.session_started_at,
                    note = EXCLUDED.note,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "sid": station.id, "lid": d.local_id, "tlid": d.tank_local_id, "det": d.detected_at,
                "start": d.start_volume_gallons, "end": d.end_volume_gallons, "gal": d.gallons_received,
                "adj": d.adjusted_gallons_received, "conf": d.confirmed, "manual": d.manual_gallons_received,
                "manconf": d.manually_confirmed_at, "cnt": d.merged_poll_count, "sess": d.session_started_at,
                "note": d.note, "upd": d.updated_at,
            },
        )
        counts["delivery_events"] += 1

    for p in batch.fuel_prices:
        db.execute(
            text(
                """
                INSERT INTO cloud_fuel_prices
                    (station_id, local_id, tank_local_id, effective_at, cost_per_gallon,
                     tax_fees_per_gallon, tax_rate_percent, sale_price_per_gallon, source,
                     note, created_at, updated_at)
                VALUES
                    (:sid, :lid, :tlid, :eff, :cost, :taxfee, :taxrate, :sale, :source,
                     :note, :created, :upd)
                ON CONFLICT (station_id, local_id) DO UPDATE SET
                    effective_at = EXCLUDED.effective_at,
                    cost_per_gallon = EXCLUDED.cost_per_gallon,
                    tax_fees_per_gallon = EXCLUDED.tax_fees_per_gallon,
                    tax_rate_percent = EXCLUDED.tax_rate_percent,
                    sale_price_per_gallon = EXCLUDED.sale_price_per_gallon,
                    source = EXCLUDED.source,
                    note = EXCLUDED.note,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "sid": station.id, "lid": p.local_id, "tlid": p.tank_local_id, "eff": p.effective_at,
                "cost": p.cost_per_gallon, "taxfee": p.tax_fees_per_gallon, "taxrate": p.tax_rate_percent,
                "sale": p.sale_price_per_gallon, "source": p.source, "note": p.note,
                "created": p.created_at, "upd": p.updated_at,
            },
        )
        counts["fuel_prices"] += 1

    for pl in batch.poll_log:
        db.execute(
            text(
                """
                INSERT INTO cloud_poll_log
                    (station_id, local_id, polled_at, success, error_message, duration_ms)
                VALUES
                    (:sid, :lid, :polled_at, :success, :err, :dur)
                ON CONFLICT (station_id, local_id) DO NOTHING
                """
            ),
            {
                "sid": station.id, "lid": pl.local_id, "polled_at": pl.polled_at,
                "success": pl.success, "err": pl.error_message, "dur": pl.duration_ms,
            },
        )
        counts["poll_log"] += 1

    # Branding is mirrored FROM the station's own local settings — the cloud
    # never sets it independently. Only touch columns the station actually
    # sent (all fields optional so a station running an older sync image
    # that never sends station_info leaves the cloud's copy untouched).
    if batch.station_info is not None:
        db.execute(
            text(
                """
                UPDATE stations SET
                    brand_preset = :preset,
                    brand_primary_color = :primary,
                    brand_secondary_color = :secondary,
                    brand_accent_color = :accent,
                    brand_logo_data_url = :logo
                WHERE id = :sid
                """
            ),
            {
                "sid": station.id,
                "preset": batch.station_info.brand_preset,
                "primary": batch.station_info.brand_primary_color,
                "secondary": batch.station_info.brand_secondary_color,
                "accent": batch.station_info.brand_accent_color,
                "logo": batch.station_info.brand_logo_data_url,
            },
        )

    now = datetime.now(tz=timezone.utc)
    db.execute(text("UPDATE stations SET last_sync_at = :now WHERE id = :sid"), {"now": now, "sid": station.id})
    db.commit()

    return IngestResult(received=counts, synced_at=now)


# ── Price updates queued from the cloud side (T1) ────────────────────────────
#
# The one narrow exception to "v1 sync is one-way": a price entered on the
# cloud's T1 dashboard is queued here, and the station's own `sync`
# container (device-credential auth, same as the push above) polls for its
# pending rows and applies them locally. See routers/stations.py's
# submit_price_update for how these get created.

@router.get("/ingest/price-updates")
def pending_price_updates(db: Session = Depends(get_db), station: Station = Depends(verify_device)):
    rows = (
        db.query(PendingPriceUpdate)
        .filter(PendingPriceUpdate.station_id == station.id, PendingPriceUpdate.applied_at.is_(None))
        .order_by(PendingPriceUpdate.created_at.asc())
        .all()
    )
    return [
        {
            "id": r.id, "tank_local_id": r.tank_local_id,
            "cost_per_gallon": float(r.cost_per_gallon) if r.cost_per_gallon is not None else None,
            "tax_rate_percent": float(r.tax_rate_percent) if r.tax_rate_percent is not None else None,
            "tax_fees_per_gallon": float(r.tax_fees_per_gallon) if r.tax_fees_per_gallon is not None else None,
            "sale_price_per_gallon": float(r.sale_price_per_gallon) if r.sale_price_per_gallon is not None else None,
            "effective_at": r.effective_at, "note": r.note,
        }
        for r in rows
    ]


@router.post("/ingest/price-updates/{update_id}/ack")
def ack_price_update(update_id: int, db: Session = Depends(get_db), station: Station = Depends(verify_device)):
    row = db.query(PendingPriceUpdate).filter(
        PendingPriceUpdate.id == update_id, PendingPriceUpdate.station_id == station.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Price update not found")
    row.applied_at = datetime.now(tz=timezone.utc)
    db.commit()
    return {"ok": True}

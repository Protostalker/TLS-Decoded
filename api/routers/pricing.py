"""
Fuel pricing / margin tracking.

Each tank gets a time series of price entries (cost, taxes/fees, sale price).
The most recent entry with effective_at <= a given time is "the price" at
that moment — this is how historical margin/profit gets computed (e.g. the
monthly ledger CSV uses whatever price was in effect on each day).

`source` distinguishes manual entries from a future automated feed (e.g. a
fuel supplier or back-office API) — POST accepts an optional `source` so an
integration can write here later without any schema changes. Nothing
automated is wired up yet; this is manual-entry only for now.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import FuelPrice, Tank
from schemas import FuelPriceCreate, FuelPriceOut, FuelPriceUpdate

router = APIRouter()


def _tax_dollars(cost: float, tax_rate_percent: Optional[float], tax_fees_per_gallon: Optional[float]) -> float:
    """Rate wins when given (the normal path) — flat dollar amount is the fallback/override."""
    if tax_rate_percent is not None:
        return round(cost * float(tax_rate_percent) / 100, 6)
    return float(tax_fees_per_gallon or 0)


def _compute(p: FuelPrice) -> FuelPriceOut:
    cost = float(p.cost_per_gallon or 0)
    tax = float(p.tax_fees_per_gallon or 0)
    sale = float(p.sale_price_per_gallon or 0)
    breakeven = round(cost + tax, 6)
    margin = round(sale - breakeven, 6)
    margin_pct = round((margin / sale) * 100, 4) if sale else None

    return FuelPriceOut(
        id=p.id,
        tank_id=p.tank_id,
        effective_at=p.effective_at,
        cost_per_gallon=cost,
        tax_rate_percent=float(p.tax_rate_percent) if p.tax_rate_percent is not None else None,
        tax_fees_per_gallon=tax,
        sale_price_per_gallon=sale,
        source=p.source,
        note=p.note,
        breakeven_per_gallon=breakeven,
        margin_per_gallon=margin,
        margin_percent=margin_pct,
    )


@router.get("/tanks/{tank_id}/prices", response_model=list[FuelPriceOut])
def list_prices(tank_id: int, limit: int = Query(20, le=200), db: Session = Depends(get_db)):
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    rows = (
        db.query(FuelPrice)
        .filter(FuelPrice.tank_id == tank_id)
        .order_by(FuelPrice.effective_at.desc())
        .limit(limit)
        .all()
    )
    return [_compute(r) for r in rows]


@router.get("/tanks/{tank_id}/prices/current", response_model=FuelPriceOut)
def current_price(tank_id: int, db: Session = Depends(get_db)):
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    now = datetime.now(tz=timezone.utc)
    row = (
        db.query(FuelPrice)
        .filter(FuelPrice.tank_id == tank_id, FuelPrice.effective_at <= now)
        .order_by(FuelPrice.effective_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No pricing set for this tank yet")
    return _compute(row)


@router.post("/tanks/{tank_id}/prices", response_model=FuelPriceOut)
def add_price(tank_id: int, body: FuelPriceCreate, db: Session = Depends(get_db)):
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")
    if body.cost_per_gallon < 0 or body.sale_price_per_gallon < 0:
        raise HTTPException(status_code=400, detail="Prices must be >= 0")
    if body.tax_rate_percent is not None and body.tax_rate_percent < 0:
        raise HTTPException(status_code=400, detail="tax_rate_percent must be >= 0")

    row = FuelPrice(
        tank_id=tank_id,
        effective_at=body.effective_at or datetime.now(tz=timezone.utc),
        cost_per_gallon=body.cost_per_gallon,
        tax_rate_percent=body.tax_rate_percent,
        tax_fees_per_gallon=_tax_dollars(body.cost_per_gallon, body.tax_rate_percent, body.tax_fees_per_gallon),
        sale_price_per_gallon=body.sale_price_per_gallon,
        source="manual",
        note=body.note,
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _compute(row)


@router.put("/prices/{price_id}", response_model=FuelPriceOut)
def update_price(price_id: int, body: FuelPriceUpdate, db: Session = Depends(get_db)):
    row = db.query(FuelPrice).filter(FuelPrice.id == price_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Price entry not found")

    if body.cost_per_gallon is not None:
        row.cost_per_gallon = body.cost_per_gallon
    if body.tax_rate_percent is not None:
        row.tax_rate_percent = body.tax_rate_percent
    if body.tax_fees_per_gallon is not None and body.tax_rate_percent is None:
        # Explicit flat-dollar override — but only if this update isn't also
        # setting a rate (rate always wins so the two can't fight).
        row.tax_rate_percent = None
        row.tax_fees_per_gallon = body.tax_fees_per_gallon
    if body.sale_price_per_gallon is not None:
        row.sale_price_per_gallon = body.sale_price_per_gallon
    if body.effective_at is not None:
        row.effective_at = body.effective_at
    if body.note is not None:
        row.note = body.note

    # Keep tax_fees_per_gallon in sync with cost whenever a rate is set —
    # covers the case where only cost_per_gallon changed this time.
    if row.tax_rate_percent is not None:
        row.tax_fees_per_gallon = _tax_dollars(float(row.cost_per_gallon or 0), float(row.tax_rate_percent), None)

    db.commit()
    db.refresh(row)
    return _compute(row)


@router.delete("/prices/{price_id}")
def delete_price(price_id: int, db: Session = Depends(get_db)):
    row = db.query(FuelPrice).filter(FuelPrice.id == price_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Price entry not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}

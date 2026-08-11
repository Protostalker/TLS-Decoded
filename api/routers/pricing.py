"""
Fuel pricing / margin tracking.

Each tank gets a time series of price entries (cost, taxes/fees, sale price).
The most recent entry with effective_at <= a given time is "the price" at
that moment — this is how historical margin/profit gets computed (e.g. the
monthly ledger CSV uses whatever price was in effect on each day).

`source` distinguishes manual entries (from the dashboard) from the hourly
commander-reader price sync (poller/commander_prices.py), which writes here
directly with source="commander_auto" for any tank with a commander_grade_id
configured.

Both cost_per_gallon and sale_price_per_gallon are independently optional on
create — whichever one is omitted carries forward from the tank's most
recent price row. This is what lets a manual entry just be "here's the new
cost" (Commander can never know wholesale cost — it only reports what's live
at the pump) and what lets the Commander sync just be "here's the new sale
price" without touching cost.

tax_rate_percent is also optional — when omitted (and no flat
tax_fees_per_gallon override given either), it defaults from the
DEFAULT_TAX_RATE_PERCENT env var so a station's tax rate is configured once
rather than re-entered on every price change.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import FuelPrice, Tank
from schemas import FuelPriceCreate, FuelPriceOut, FuelPriceUpdate

router = APIRouter()


def _default_tax_rate_percent() -> Optional[float]:
    raw = os.environ.get("DEFAULT_TAX_RATE_PERCENT")
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _latest_price(db: Session, tank_id: int) -> Optional[FuelPrice]:
    return (
        db.query(FuelPrice)
        .filter(FuelPrice.tank_id == tank_id)
        .order_by(FuelPrice.effective_at.desc())
        .first()
    )


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
    if body.cost_per_gallon is not None and body.cost_per_gallon < 0:
        raise HTTPException(status_code=400, detail="Prices must be >= 0")
    if body.sale_price_per_gallon is not None and body.sale_price_per_gallon < 0:
        raise HTTPException(status_code=400, detail="Prices must be >= 0")
    if body.tax_rate_percent is not None and body.tax_rate_percent < 0:
        raise HTTPException(status_code=400, detail="tax_rate_percent must be >= 0")

    prior = _latest_price(db, tank_id)

    cost = body.cost_per_gallon if body.cost_per_gallon is not None else (
        float(prior.cost_per_gallon) if prior and prior.cost_per_gallon is not None else None
    )
    sale = body.sale_price_per_gallon if body.sale_price_per_gallon is not None else (
        float(prior.sale_price_per_gallon) if prior and prior.sale_price_per_gallon is not None else None
    )
    if cost is None or sale is None:
        raise HTTPException(
            status_code=400,
            detail="cost_per_gallon and sale_price_per_gallon are both required the first time "
                   "a price is set for a tank (nothing to carry forward yet).",
        )

    tax_rate = body.tax_rate_percent
    if tax_rate is None and body.tax_fees_per_gallon is None:
        tax_rate = _default_tax_rate_percent()

    row = FuelPrice(
        tank_id=tank_id,
        effective_at=body.effective_at or datetime.now(tz=timezone.utc),
        cost_per_gallon=cost,
        tax_rate_percent=tax_rate,
        tax_fees_per_gallon=_tax_dollars(cost, tax_rate, body.tax_fees_per_gallon),
        sale_price_per_gallon=sale,
        source=body.source or "manual",
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
    # covers the case where only cost_per_gallon changed this time. Falls
    # back to DEFAULT_TAX_RATE_PERCENT if this row never had a rate at all
    # (e.g. it predates the env-var default being configured).
    effective_rate = row.tax_rate_percent
    if effective_rate is None and body.tax_fees_per_gallon is None:
        effective_rate = _default_tax_rate_percent()
    if effective_rate is not None:
        row.tax_rate_percent = effective_rate
        row.tax_fees_per_gallon = _tax_dollars(float(row.cost_per_gallon or 0), float(effective_rate), None)

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

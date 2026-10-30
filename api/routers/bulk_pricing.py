"""
Bulk (day-by-day) pricing for the current month.

For catching up after a stretch of not entering prices: wholesale cost comes
in once a day (~6 AM) and the pump price can change at any time, but this
page only deals in ONE cost + ONE sale price per tank per day, both
effective 06:00 station-local. Mid-day changes can still be added afterward
with the normal "Update price" form (or arrive via Commander sync).

Days the user leaves blank need no row at all: margin lookups are
point-in-time ("most recent row with effective_at <= t"), so a blank day just
continues the previous day's price.

Cost propagation: Commander sync inserts its own rows mid-day, carrying
forward whatever cost was current at the time — which, if the cost for that
day hadn't been entered yet, is stale. When a bulk entry sets a cost, it is
therefore also written onto the commander_auto rows that follow it, up to
(not including) the next manually-entered row, so the cost actually sticks
for the whole day instead of being overridden at the next Commander tick.
Sale prices on those rows are never touched.
"""
import os
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import FuelPrice, Setting, Tank
from routers.insights import STATION_TZ

router = APIRouter()

PRICE_HOUR = 6  # wholesale prices arrive ~6 AM


def _boundary(d: date) -> datetime:
    """06:00 station-local on day d, as an aware UTC datetime."""
    return datetime.combine(d, time(PRICE_HOUR, 0), tzinfo=STATION_TZ).astimezone(timezone.utc)


def _setting_float(db: Session, key: str, env: str) -> Optional[float]:
    row = db.query(Setting).filter(Setting.key == key).first()
    raw = (row.value if row else None) or os.environ.get(env)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _today_local() -> date:
    return datetime.now(tz=STATION_TZ).date()


class BulkCell(BaseModel):
    cost_per_gallon: Optional[float] = None
    sale_price_per_gallon: Optional[float] = None
    entered: bool = False  # an explicit 6 AM row exists for this day


class BulkTankOut(BaseModel):
    id: int
    name: str
    product: Optional[str] = None
    days: dict[str, BulkCell]  # ISO date -> cell


class BulkMonthOut(BaseModel):
    month: str
    days: list[str]
    tanks: list[BulkTankOut]


class BulkEntry(BaseModel):
    tank_id: int
    date: date
    cost_per_gallon: Optional[float] = None
    sale_price_per_gallon: Optional[float] = None


class BulkSave(BaseModel):
    entries: list[BulkEntry]


@router.get("/prices/bulk", response_model=BulkMonthOut)
def get_bulk_month(month: Optional[str] = Query(None, description="YYYY-MM, default current month"),
                   db: Session = Depends(get_db)):
    today = _today_local()
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            first = date(y, m, 1)
        except Exception:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    else:
        first = today.replace(day=1)
    last = min(date(first.year, first.month, monthrange(first.year, first.month)[1]), today)
    days: list[date] = []
    d = first
    while d <= last:
        days.append(d)
        d += timedelta(days=1)

    tanks = db.query(Tank).filter(Tank.active == True).order_by(Tank.id).all()  # noqa: E712
    out: list[BulkTankOut] = []
    for t in tanks:
        rows = (
            db.query(FuelPrice)
            .filter(FuelPrice.tank_id == t.id)
            .order_by(FuelPrice.effective_at.asc())
            .all()
        )
        cells: dict[str, BulkCell] = {}
        idx = -1
        for day in days:
            b = _boundary(day)
            exact = False
            while idx + 1 < len(rows) and rows[idx + 1].effective_at <= b:
                idx += 1
            applicable = rows[idx] if idx >= 0 else None
            if applicable is not None and applicable.effective_at == b:
                exact = True
            cells[day.isoformat()] = BulkCell(
                cost_per_gallon=float(applicable.cost_per_gallon) if applicable and applicable.cost_per_gallon is not None else None,
                sale_price_per_gallon=float(applicable.sale_price_per_gallon) if applicable and applicable.sale_price_per_gallon is not None else None,
                entered=exact,
            )
        out.append(BulkTankOut(id=t.id, name=t.name, product=t.product, days=cells))

    return BulkMonthOut(month=first.strftime("%Y-%m"), days=[x.isoformat() for x in days], tanks=out)


@router.post("/prices/bulk")
def save_bulk(body: BulkSave, db: Session = Depends(get_db)):
    today = _today_local()
    default_rate = _setting_float(db, "default_tax_rate_percent", "DEFAULT_TAX_RATE_PERCENT")
    default_fee = _setting_float(db, "default_additional_fee_per_gallon", "DEFAULT_ADDITIONAL_FEE_PER_GALLON")

    entries = sorted(body.entries, key=lambda e: (e.tank_id, e.date))
    tank_ids = {e.tank_id for e in entries}
    known = {t.id for t in db.query(Tank).filter(Tank.id.in_(tank_ids)).all()} if tank_ids else set()

    for e in entries:
        if e.tank_id not in known:
            raise HTTPException(status_code=404, detail=f"Tank {e.tank_id} not found")
        if e.date > today:
            raise HTTPException(status_code=400, detail=f"{e.date}: can't enter prices for a future day")
        if e.cost_per_gallon is None and e.sale_price_per_gallon is None:
            raise HTTPException(status_code=400, detail=f"{e.date}: enter a cost, a sale price, or both")
        if (e.cost_per_gallon is not None and e.cost_per_gallon < 0) or \
           (e.sale_price_per_gallon is not None and e.sale_price_per_gallon < 0):
            raise HTTPException(status_code=400, detail=f"{e.date}: prices must be >= 0")

    created = updated = 0
    now = datetime.now(tz=timezone.utc)

    for e in entries:
        b = _boundary(e.date)
        existing = (
            db.query(FuelPrice)
            .filter(FuelPrice.tank_id == e.tank_id, FuelPrice.effective_at == b)
            .first()
        )
        if existing:
            row = existing
            if e.cost_per_gallon is not None:
                row.cost_per_gallon = e.cost_per_gallon
            if e.sale_price_per_gallon is not None:
                row.sale_price_per_gallon = e.sale_price_per_gallon
            rate = float(row.tax_rate_percent) if row.tax_rate_percent is not None else default_rate
            if rate is not None:
                row.tax_rate_percent = rate
                row.tax_fees_per_gallon = round(float(row.cost_per_gallon or 0) * rate / 100, 6)
            updated += 1
        else:
            prior = (
                db.query(FuelPrice)
                .filter(FuelPrice.tank_id == e.tank_id, FuelPrice.effective_at < b)
                .order_by(FuelPrice.effective_at.desc())
                .first()
            )
            cost = e.cost_per_gallon if e.cost_per_gallon is not None else (
                float(prior.cost_per_gallon) if prior and prior.cost_per_gallon is not None else None)
            sale = e.sale_price_per_gallon if e.sale_price_per_gallon is not None else (
                float(prior.sale_price_per_gallon) if prior and prior.sale_price_per_gallon is not None else None)
            if cost is None or sale is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"{e.date}: no earlier price to carry forward for tank {e.tank_id} — "
                           "enter both cost and sale price for the first day.",
                )
            fee = float(prior.additional_fee_per_gallon) if prior and prior.additional_fee_per_gallon is not None else default_fee
            row = FuelPrice(
                tank_id=e.tank_id,
                effective_at=b,
                cost_per_gallon=cost,
                tax_rate_percent=default_rate,
                tax_fees_per_gallon=round(cost * default_rate / 100, 6) if default_rate is not None else 0,
                additional_fee_per_gallon=fee,
                sale_price_per_gallon=sale,
                source="manual",
                note="Bulk entry",
                created_at=now,
            )
            db.add(row)
            created += 1
        db.flush()

        # Make a newly-set cost stick through the day's Commander rows (see module docstring).
        if e.cost_per_gallon is not None:
            next_manual = (
                db.query(FuelPrice.effective_at)
                .filter(FuelPrice.tank_id == e.tank_id, FuelPrice.effective_at > b,
                        FuelPrice.source != "commander_auto")
                .order_by(FuelPrice.effective_at.asc())
                .first()
            )
            q = db.query(FuelPrice).filter(
                FuelPrice.tank_id == e.tank_id, FuelPrice.effective_at > b,
                FuelPrice.source == "commander_auto",
            )
            if next_manual:
                q = q.filter(FuelPrice.effective_at < next_manual[0])
            for r in q.all():
                r.cost_per_gallon = e.cost_per_gallon
                rate = float(r.tax_rate_percent) if r.tax_rate_percent is not None else default_rate
                if rate is not None:
                    r.tax_rate_percent = rate
                    r.tax_fees_per_gallon = round(e.cost_per_gallon * rate / 100, 6)

    db.commit()
    return {"created": created, "updated": updated}

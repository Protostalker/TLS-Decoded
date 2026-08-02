"""Monthly CSV export endpoints — per-tank, all-tanks-combined, and a
day-by-day ledger summary (gallons on hand / added / sold) matching the
station's existing manual spreadsheet format."""
import csv
import io
import os
import re
from calendar import monthrange
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models import DeliveryEvent, Reading, Tank

router = APIRouter()

# Station's local timezone — used to bucket readings/deliveries into
# accounting days for the monthly ledger summary (Gardena, CA).
STATION_TZ = ZoneInfo(os.environ.get("STATION_TZ", "America/Los_Angeles"))

# The ledger's "day" doesn't roll over at midnight — it rolls over at this
# local hour, matching the station's historical manual-reading convention
# (a reading taken at/after this hour "closes the books" for the day whose
# window just ended). Picked at 2am specifically because deliveries almost
# never happen then, so a delivery essentially never straddles the boundary.
LEDGER_DAY_ROLLOVER_HOUR = int(os.environ.get("LEDGER_ROLLOVER_HOUR", "2"))
_ROLLOVER_TIME = dtime(LEDGER_DAY_ROLLOVER_HOUR, 0, 0)


def _accounting_date(dt: datetime) -> date:
    """
    Map a UTC timestamp to the ledger "day" it belongs to.

    A day's window is (rollover time on day N-1, rollover time on day N] —
    i.e. GAL(day N) is the closing reading taken at day N's rollover time,
    and anything after that rollover (the normal case for daytime deliveries)
    belongs to the *next* day's window. This mirrors the station's original
    manual process, where a delivery couldn't be confirmed/logged until the
    following day's reading closed the books on it.
    """
    local = dt.astimezone(STATION_TZ)
    if local.time() <= _ROLLOVER_TIME:
        return local.date()
    return local.date() + timedelta(days=1)


def _rollover_at(d: date) -> datetime:
    """The exact local rollover instant for calendar date `d`."""
    return datetime.combine(d, _ROLLOVER_TIME, tzinfo=STATION_TZ)

_KNOWN_ABBR = {
    "unleaded": "UNL", "regular": "UNL", "super": "SUP", "premium": "PRM",
    "diesel": "DSL", "midgrade": "MID", "plus": "PLS",
}


def _abbr(name: str) -> str:
    key = (name or "").strip().lower()
    if key in _KNOWN_ABBR:
        return _KNOWN_ABBR[key]
    letters = re.sub(r"[^A-Za-z]", "", name or "").upper()
    return letters[:3] or "TNK"

READING_HEADER = [
    "polled_at",
    "volume_gallons",
    "ullage_gallons",
    "height_inches",
    "water_inches",
    "temperature_f",
]


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day = monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return start, end


def _csv_response(rows: list[list], header: list[str], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tanks/{tank_id}/export")
def export_tank_month(
    tank_id: int,
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    start, end = _month_bounds(year, month)
    readings = (
        db.query(Reading)
        .filter(
            Reading.tank_id == tank_id,
            Reading.polled_at >= start,
            Reading.polled_at <= end,
        )
        .order_by(Reading.polled_at.asc())
        .all()
    )
    rows = [
        [
            r.polled_at.isoformat(),
            r.volume_gallons,
            r.ullage_gallons,
            r.height_inches,
            r.water_inches,
            r.temperature_f,
        ]
        for r in readings
    ]
    filename = f"{tank.name.replace(' ', '_')}_{year:04d}-{month:02d}.csv"
    return _csv_response(rows, READING_HEADER, filename)


@router.get("/export/monthly-summary")
def export_monthly_summary(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    """
    Day-by-day ledger CSV shaped like the station's existing manual sheet:
    Day, {TANK}GAL..., {TANK}ADDED..., {TANK}SOLD..., TOTALGALSOLD

    The "day" here isn't a calendar day — it rolls over at
    LEDGER_DAY_ROLLOVER_HOUR (2am local by default), matching the station's
    historical manual-reading convention. Concretely:

    GAL   = closing volume reading at/nearest-before that day's rollover time
    ADDED = gallons from deliveries detected in the window ending at that
            rollover — since deliveries almost always happen during the day
            (after the rollover hour), they land on the *next* day's row,
            same as the old manual process.
    SOLD  = opening_volume + ADDED - closing_volume (derived, not directly polled)

    Blank cells mean "no data for that tank/day" rather than a real zero.
    """
    tanks = db.query(Tank).filter(Tank.active == True).order_by(Tank.id).all()
    if not tanks:
        raise HTTPException(status_code=404, detail="No tanks configured")
    tank_ids = [t.id for t in tanks]
    abbrs = [_abbr(t.name) for t in tanks]

    last_day = monthrange(year, month)[1]
    first_date = date(year, month, 1)
    last_date = date(year, month, last_day)

    # Ledger day N's window is (rollover(N-1), rollover(N)], so day 1 starts
    # right after the rollover on the last day of the *previous* month, and
    # the month's data ends at the rollover on this month's last day. Pad the
    # query range a bit further on both sides so nothing at the edges gets
    # missed regardless of poll timing.
    query_start = (_rollover_at(first_date - timedelta(days=2))).astimezone(timezone.utc)
    query_end = (_rollover_at(last_date + timedelta(days=1))).astimezone(timezone.utc)

    # Closing volume per tank per ledger day (last reading in that day's
    # window wins — which, since polling is clock-aligned, is normally the
    # exact reading taken at the rollover instant).
    closings: dict[int, dict[date, float]] = {tid: {} for tid in tank_ids}
    readings = (
        db.query(Reading)
        .filter(
            Reading.tank_id.in_(tank_ids),
            Reading.polled_at > query_start,
            Reading.polled_at <= query_end,
        )
        .order_by(Reading.polled_at.asc())
        .all()
    )
    for r in readings:
        if r.volume_gallons is None:
            continue
        closings[r.tank_id][_accounting_date(r.polled_at)] = r.volume_gallons  # last write wins

    # Opening balance for day 1 = most recent reading before day 1's window started.
    day1_window_start = _rollover_at(first_date - timedelta(days=1)).astimezone(timezone.utc)
    opening_carry: dict[int, float | None] = {}
    for t in tanks:
        prev = (
            db.query(Reading)
            .filter(
                Reading.tank_id == t.id,
                Reading.polled_at <= day1_window_start,
                Reading.volume_gallons.isnot(None),
            )
            .order_by(Reading.polled_at.desc())
            .first()
        )
        opening_carry[t.id] = prev.volume_gallons if prev else None

    # Deliveries (gallons added) per tank per ledger day — a delivery starting
    # anytime after a day's rollover (the normal case) lands on the next day.
    added: dict[int, dict[date, float]] = {tid: {} for tid in tank_ids}
    deliveries = (
        db.query(DeliveryEvent)
        .filter(
            DeliveryEvent.tank_id.in_(tank_ids),
            DeliveryEvent.detected_at > query_start,
            DeliveryEvent.detected_at <= query_end,
        )
        .all()
    )
    for d in deliveries:
        gallons = d.manual_gallons_received if d.manual_gallons_received is not None else d.gallons_received
        aday = _accounting_date(d.detected_at)
        added[d.tank_id][aday] = added[d.tank_id].get(aday, 0.0) + (gallons or 0.0)

    header = (
        ["Day"]
        + [f"{a}GAL" for a in abbrs]
        + [f"{a}ADDED" for a in abbrs]
        + [f"{a}SOLD" for a in abbrs]
        + ["TOTALGALSOLD"]
    )

    rows = []
    for day_num in range(1, last_day + 1):
        d = date(year, month, day_num)
        gal_cells, added_cells, sold_cells = [], [], []
        day_total_sold = 0.0
        any_sold = False

        for t in tanks:
            close = closings[t.id].get(d)
            add = added[t.id].get(d, 0.0)
            opening = opening_carry.get(t.id)

            gal_cells.append(round(close) if close is not None else "")
            added_cells.append(round(add) if add else "")

            if close is not None and opening is not None:
                sold = opening + add - close
                sold_cells.append(round(sold))
                day_total_sold += sold
                any_sold = True
            else:
                sold_cells.append("")

            if close is not None:
                opening_carry[t.id] = close  # roll forward for the next day

        row = [day_num] + gal_cells + added_cells + sold_cells
        row.append(round(day_total_sold) if any_sold else "")
        rows.append(row)

    filename = f"monthly_summary_{year:04d}-{month:02d}.csv"
    return _csv_response(rows, header, filename)


@router.get("/export")
def export_all_month(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    start, end = _month_bounds(year, month)
    rows_q = (
        db.query(Reading, Tank.name)
        .join(Tank, Tank.id == Reading.tank_id)
        .filter(Reading.polled_at >= start, Reading.polled_at <= end)
        .order_by(Reading.polled_at.asc(), Tank.id.asc())
        .all()
    )
    rows = [
        [
            tank_name,
            r.tank_id,
            r.polled_at.isoformat(),
            r.volume_gallons,
            r.ullage_gallons,
            r.height_inches,
            r.water_inches,
            r.temperature_f,
        ]
        for r, tank_name in rows_q
    ]
    filename = f"all_tanks_{year:04d}-{month:02d}.csv"
    return _csv_response(rows, ["tank_name", "tank_id"] + READING_HEADER, filename)

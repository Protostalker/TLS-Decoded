"""Operator control over delivery (fuel-added) records: confirm/correct an
auto-detected total, or manually log a delivery that auto-detection missed
entirely (e.g. it stayed under the jump threshold)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import DeliveryEvent, Tank
from schemas import DeliveryConfirm, DeliveryEventOut, DeliveryManualCreate

router = APIRouter()


@router.put("/deliveries/{delivery_id}", response_model=DeliveryEventOut)
def confirm_delivery(delivery_id: int, body: DeliveryConfirm, db: Session = Depends(get_db)):
    """
    Operator confirms or corrects the total for a delivery session (e.g. the
    driver's paper ticket says 6015 gal, but our net-change math shows 6000
    because ~15 gal sold during the fill). Once set, the poller will not
    merge further poll-to-poll jumps into this session or overwrite this
    number — a later jump starts a new session instead.
    """
    event = db.query(DeliveryEvent).filter(DeliveryEvent.id == delivery_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Delivery not found")

    if body.gallons_received < 0:
        raise HTTPException(status_code=400, detail="gallons_received must be >= 0")

    event.manual_gallons_received = body.gallons_received
    event.manually_confirmed_at = datetime.now(tz=timezone.utc)
    if body.note is not None:
        event.note = body.note

    db.commit()
    db.refresh(event)
    return _to_out(event)


@router.post("/tanks/{tank_id}/deliveries", response_model=DeliveryEventOut)
def log_manual_delivery(tank_id: int, body: DeliveryManualCreate, db: Session = Depends(get_db)):
    """Manually report a delivery that wasn't auto-detected."""
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")
    if body.gallons_received <= 0:
        raise HTTPException(status_code=400, detail="gallons_received must be positive")

    detected_at = body.detected_at or datetime.now(tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)

    event = DeliveryEvent(
        tank_id=tank_id,
        detected_at=detected_at,
        start_volume_gallons=None,
        end_volume_gallons=None,
        gallons_received=body.gallons_received,
        adjusted_gallons_received=body.gallons_received,
        confirmed=True,
        manual_gallons_received=body.gallons_received,
        manually_confirmed_at=now,
        merged_poll_count=1,
        session_started_at=detected_at,
        note=body.note,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _to_out(event)


def _to_out(e: DeliveryEvent) -> DeliveryEventOut:
    out = DeliveryEventOut.model_validate(e)
    out.effective_gallons_received = (
        e.manual_gallons_received
        if e.manual_gallons_received is not None
        else (e.adjusted_gallons_received if e.adjusted_gallons_received is not None else e.gallons_received)
    )
    return out

"""Tank endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models import Reading, Tank
from schemas import ReadingOut, TankOut, TankUpdate

router = APIRouter()


def _latest_reading(db: Session, tank_id: int) -> Reading | None:
    return (
        db.query(Reading)
        .filter(Reading.tank_id == tank_id)
        .order_by(Reading.polled_at.desc())
        .first()
    )


@router.get("/tanks", response_model=list[TankOut])
def list_tanks(db: Session = Depends(get_db)):
    tanks = db.query(Tank).filter(Tank.active == True).order_by(Tank.id).all()
    result = []
    for tank in tanks:
        tank_out = TankOut.model_validate(tank)
        latest = _latest_reading(db, tank.id)
        tank_out.latest_reading = ReadingOut.model_validate(latest) if latest else None
        result.append(tank_out)
    return result


@router.get("/tanks/{tank_id}", response_model=TankOut)
def get_tank(tank_id: int, db: Session = Depends(get_db)):
    tank = db.query(Tank).filter(Tank.id == tank_id, Tank.active == True).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")
    tank_out = TankOut.model_validate(tank)
    latest = _latest_reading(db, tank.id)
    tank_out.latest_reading = ReadingOut.model_validate(latest) if latest else None
    return tank_out


@router.put("/tanks/{tank_id}", response_model=TankOut)
def update_tank(tank_id: int, update: TankUpdate, db: Session = Depends(get_db)):
    """
    Manually correct tank config (capacity, reorder threshold, name, product) —
    e.g. when the physically-installed tank size differs from the initial YAML
    estimate. Once set here, the poller will no longer overwrite these fields
    from tls-decoded.yaml on subsequent syncs.
    """
    tank = db.query(Tank).filter(Tank.id == tank_id).first()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    if update.name is not None:
        tank.name = update.name
    if update.product is not None:
        tank.product = update.product
    if update.capacity_gallons is not None:
        if update.capacity_gallons <= 0:
            raise HTTPException(status_code=400, detail="capacity_gallons must be positive")
        tank.capacity_gallons = update.capacity_gallons
    if update.reorder_threshold_gallons is not None:
        if update.reorder_threshold_gallons < 0:
            raise HTTPException(status_code=400, detail="reorder_threshold_gallons must be >= 0")
        tank.reorder_threshold_gallons = update.reorder_threshold_gallons

    db.commit()
    db.refresh(tank)

    tank_out = TankOut.model_validate(tank)
    latest = _latest_reading(db, tank.id)
    tank_out.latest_reading = ReadingOut.model_validate(latest) if latest else None
    return tank_out

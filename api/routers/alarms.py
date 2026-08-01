"""Alarm endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Alarm
from schemas import AlarmOut

router = APIRouter()


@router.get("/alarms", response_model=list[AlarmOut])
def active_alarms(db: Session = Depends(get_db)):
    alarms = (
        db.query(Alarm)
        .filter(Alarm.active == True)
        .order_by(Alarm.detected_at.desc())
        .all()
    )
    return [AlarmOut.model_validate(a) for a in alarms]


@router.get("/alarms/history", response_model=list[AlarmOut])
def alarm_history(
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
):
    alarms = (
        db.query(Alarm)
        .order_by(Alarm.detected_at.desc())
        .limit(limit)
        .all()
    )
    return [AlarmOut.model_validate(a) for a in alarms]

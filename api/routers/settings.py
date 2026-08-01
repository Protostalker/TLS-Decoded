"""Runtime settings endpoints — poll interval, clock alignment, manual poll trigger,
device id (for future cloud sync), and remote-sync placeholders.

Settings are stored as key/value rows in the `settings` table so the poller (a
separate process) can read live changes without a restart — see poller/main.py's
scheduling loop, which re-reads these every ~15s.
"""
import os
import re
import secrets
from datetime import datetime, timezone

import yaml
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Setting
from schemas import DeviceIdOut, SettingsOut, SettingsUpdate

router = APIRouter()

# Preset choices surfaced in the frontend dropdown; PUT still accepts any
# value between 1 and 1440 minutes for custom intervals.
AVAILABLE_INTERVALS = [5, 10, 15, 20, 30, 60, 120, 180, 240]


def _yaml_defaults() -> dict:
    try:
        cfg_path = os.environ.get("CONFIG_PATH", "/app/config/tls-decoded.yaml")
        with open(cfg_path) as f:
            raw = yaml.safe_load(f)
        polling = raw.get("polling", {})
        remote = raw.get("remote", {})
        return {
            "poll_interval_minutes": str(polling.get("interval_minutes", 60)),
            "poll_aligned": "true",
            "device_id": remote.get("device_id") or secrets.token_hex(16),
            "remote_enabled": "true" if remote.get("enabled") else "false",
            "remote_server_url": remote.get("server_url", "") or "",
            "poll_now_requested_at": "",
        }
    except Exception:
        return {
            "poll_interval_minutes": "60",
            "poll_aligned": "true",
            "device_id": secrets.token_hex(16),
            "remote_enabled": "false",
            "remote_server_url": "",
            "poll_now_requested_at": "",
        }


def _get_all(db: Session) -> dict[str, str]:
    """Read all settings rows, seeding any missing keys with YAML/generated defaults."""
    rows = db.query(Setting).all()
    values = {r.key: (r.value or "") for r in rows}
    defaults = _yaml_defaults()
    missing = {k: v for k, v in defaults.items() if k not in values}
    if missing:
        for k, v in missing.items():
            db.merge(Setting(key=k, value=v))
        db.commit()
        values.update(missing)
    return values


def _set(db: Session, key: str, value: str) -> None:
    db.merge(Setting(key=key, value=value))
    db.commit()


def _to_out(v: dict[str, str]) -> SettingsOut:
    return SettingsOut(
        poll_interval_minutes=int(v.get("poll_interval_minutes") or 60),
        poll_aligned=(v.get("poll_aligned") or "true").lower() == "true",
        available_intervals=AVAILABLE_INTERVALS,
        device_id=v.get("device_id") or "",
        remote_enabled=(v.get("remote_enabled") or "false").lower() == "true",
        remote_server_url=v.get("remote_server_url") or "",
        poll_now_pending=bool(v.get("poll_now_requested_at")),
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return _to_out(_get_all(db))


@router.put("/settings", response_model=SettingsOut)
def update_settings(update: SettingsUpdate, db: Session = Depends(get_db)):
    _get_all(db)  # ensure defaults exist before partial update

    if update.poll_interval_minutes is not None:
        if not (1 <= update.poll_interval_minutes <= 1440):
            raise HTTPException(
                status_code=400,
                detail="poll_interval_minutes must be between 1 and 1440",
            )
        _set(db, "poll_interval_minutes", str(update.poll_interval_minutes))

    if update.poll_aligned is not None:
        _set(db, "poll_aligned", "true" if update.poll_aligned else "false")

    if update.remote_enabled is not None:
        _set(db, "remote_enabled", "true" if update.remote_enabled else "false")

    if update.remote_server_url is not None:
        _set(db, "remote_server_url", update.remote_server_url)

    if update.device_id is not None:
        candidate = update.device_id.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8,64}", candidate):
            raise HTTPException(
                status_code=400,
                detail="device_id must be 8-64 hex characters (0-9, a-f)",
            )
        _set(db, "device_id", candidate)

    return _to_out(_get_all(db))


@router.post("/settings/poll-now")
def trigger_poll_now(db: Session = Depends(get_db)):
    """Ask the poller to run an out-of-cycle poll on its next tick (~15s)."""
    _get_all(db)
    _set(db, "poll_now_requested_at", datetime.now(tz=timezone.utc).isoformat())
    return {"status": "requested"}


@router.post("/settings/device-id/regenerate", response_model=DeviceIdOut)
def regenerate_device_id(db: Session = Depends(get_db)):
    new_id = secrets.token_hex(16)
    _set(db, "device_id", new_id)
    return DeviceIdOut(device_id=new_id)

"""Runtime settings endpoints — poll interval, clock alignment, manual poll trigger,
device id (for future cloud sync), and remote-sync placeholders.

Settings are stored as key/value rows in the `settings` table so other
processes (poller, and now sync) can read live changes without a restart —
see poller/main.py's scheduling loop, which re-reads these every ~15s, and
sync/main.py's loop, which does the same for cloud_sync_* keys.
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


def _cloud_sync_defaults() -> dict:
    """cloud_sync_* keys aren't sourced from tls-decoded.yaml (no schema
    entry there — see sync/config.py's own env-var loader) — they're
    normally seeded by the sync container on its first boot. These are only
    a fallback so /settings never 404s on a fresh DB before sync has run
    (e.g. right after `docker compose up` on a station that hasn't started
    the sync container yet)."""
    return {
        "cloud_sync_enabled": "false",
        "cloud_sync_url": "",
        "cloud_sync_device_id": "",
        "cloud_sync_device_secret": "",
        "cloud_sync_interval_minutes": "30",
        "cloud_sync_last_synced_at": "",
    }


def _get_all(db: Session) -> dict[str, str]:
    """Read all settings rows, seeding any missing keys with YAML/generated defaults."""
    rows = db.query(Setting).all()
    values = {r.key: (r.value or "") for r in rows}
    defaults = {**_yaml_defaults(), **_cloud_sync_defaults()}
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
    last_synced_raw = v.get("cloud_sync_last_synced_at") or ""
    last_synced = None
    if last_synced_raw:
        try:
            last_synced = datetime.fromisoformat(last_synced_raw)
        except ValueError:
            last_synced = None

    return SettingsOut(
        poll_interval_minutes=int(v.get("poll_interval_minutes") or 60),
        poll_aligned=(v.get("poll_aligned") or "true").lower() == "true",
        available_intervals=AVAILABLE_INTERVALS,
        device_id=v.get("device_id") or "",
        remote_enabled=(v.get("remote_enabled") or "false").lower() == "true",
        remote_server_url=v.get("remote_server_url") or "",
        poll_now_pending=bool(v.get("poll_now_requested_at")),
        cloud_sync_enabled=(v.get("cloud_sync_enabled") or "false").lower() == "true",
        cloud_sync_url=v.get("cloud_sync_url") or "",
        cloud_sync_device_id=v.get("cloud_sync_device_id") or "",
        cloud_sync_device_secret=v.get("cloud_sync_device_secret") or "",
        cloud_sync_interval_minutes=int(v.get("cloud_sync_interval_minutes") or 30),
        cloud_sync_last_synced_at=last_synced,
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

    # ── Cloud sync (cloud/) — picked up by the sync container on its next
    #    ~15s tick, no restart needed, same as poll_interval_minutes above. ──
    if update.cloud_sync_enabled is not None:
        _set(db, "cloud_sync_enabled", "true" if update.cloud_sync_enabled else "false")

    if update.cloud_sync_url is not None:
        candidate = update.cloud_sync_url.strip().rstrip("/")
        if candidate and not re.match(r"^https?://", candidate):
            raise HTTPException(status_code=400, detail="cloud_sync_url must start with http:// or https://")
        _set(db, "cloud_sync_url", candidate)

    if update.cloud_sync_device_id is not None:
        _set(db, "cloud_sync_device_id", update.cloud_sync_device_id.strip())

    if update.cloud_sync_device_secret is not None:
        _set(db, "cloud_sync_device_secret", update.cloud_sync_device_secret.strip())

    if update.cloud_sync_interval_minutes is not None:
        if not (1 <= update.cloud_sync_interval_minutes <= 1440):
            raise HTTPException(
                status_code=400,
                detail="cloud_sync_interval_minutes must be between 1 and 1440",
            )
        _set(db, "cloud_sync_interval_minutes", str(update.cloud_sync_interval_minutes))

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

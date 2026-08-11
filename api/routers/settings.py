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

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Setting
from schemas import CommanderGradeOut, CommanderTestOut, DeviceIdOut, SettingsOut, SettingsUpdate

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


def _brand_defaults() -> dict:
    """Branding — theme colors + logo for this station's dashboard. Empty
    string logo means 'no custom logo, show the generated monogram badge'.
    Colors default to the app's original blue/indigo so an unbranded
    install looks exactly like it always has."""
    return {
        "brand_preset": "default",
        "brand_primary_color": "#3b82f6",
        "brand_secondary_color": "#6366f1",
        "brand_accent_color": "#3b82f6",
        "brand_logo_data_url": "",
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


def _commander_defaults() -> dict:
    """Commander price sync — normally seeded by the poller on its first
    boot (poller/main.py's seed_settings(), from the COMMANDER_READER_URL /
    COMMANDER_PRICE_TIER / COMMANDER_PRICE_SYNC_INTERVAL_MINUTES env vars).
    This is only a fallback so /settings never 404s before the poller has
    run — same reasoning as _cloud_sync_defaults() above. A station with no
    Commander (or an operator who won't allow the integration) just leaves
    this disabled/blank forever; nothing else depends on it."""
    return {
        "commander_sync_enabled": "false",
        "commander_reader_url": "",
        "commander_price_tier": "cash",
        "commander_sync_interval_minutes": "60",
        "commander_last_check_at": "",
        "commander_last_connected": "",
        "commander_last_error": "",
        "default_tax_rate_percent": os.environ.get("DEFAULT_TAX_RATE_PERCENT", ""),
    }


def _get_all(db: Session) -> dict[str, str]:
    """Read all settings rows, seeding any missing keys with YAML/generated defaults."""
    rows = db.query(Setting).all()
    values = {r.key: (r.value or "") for r in rows}
    defaults = {**_yaml_defaults(), **_cloud_sync_defaults(), **_commander_defaults(), **_brand_defaults()}
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

    commander_check_raw = v.get("commander_last_check_at") or ""
    commander_check_at = None
    if commander_check_raw:
        try:
            commander_check_at = datetime.fromisoformat(commander_check_raw)
        except ValueError:
            commander_check_at = None
    commander_connected_raw = v.get("commander_last_connected") or ""
    commander_connected = {"true": True, "false": False}.get(commander_connected_raw)

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
        commander_sync_enabled=(v.get("commander_sync_enabled") or "false").lower() == "true",
        commander_reader_url=v.get("commander_reader_url") or "",
        commander_price_tier=v.get("commander_price_tier") or "cash",
        commander_sync_interval_minutes=int(v.get("commander_sync_interval_minutes") or 60),
        commander_last_check_at=commander_check_at,
        commander_last_connected=commander_connected,
        commander_last_error=v.get("commander_last_error") or None,
        default_tax_rate_percent=(
            float(v["default_tax_rate_percent"])
            if (v.get("default_tax_rate_percent") or "").strip() else None
        ),
        brand_preset=v.get("brand_preset") or "default",
        brand_primary_color=v.get("brand_primary_color") or "#3b82f6",
        brand_secondary_color=v.get("brand_secondary_color") or "#6366f1",
        brand_accent_color=v.get("brand_accent_color") or "#3b82f6",
        brand_logo_data_url=v.get("brand_logo_data_url") or "",
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

    # ── Commander price sync — picked up by the poller on its next ~15s
    #    tick, no restart needed, same as poll_interval_minutes above. ──────
    if update.commander_sync_enabled is not None:
        _set(db, "commander_sync_enabled", "true" if update.commander_sync_enabled else "false")

    if update.commander_reader_url is not None:
        candidate = update.commander_reader_url.strip().rstrip("/")
        if candidate and not re.match(r"^https?://", candidate):
            raise HTTPException(status_code=400, detail="commander_reader_url must start with http:// or https://")
        _set(db, "commander_reader_url", candidate)

    if update.commander_price_tier is not None:
        candidate = update.commander_price_tier.strip().lower()
        if candidate not in ("cash", "credit"):
            raise HTTPException(status_code=400, detail="commander_price_tier must be 'cash' or 'credit'")
        _set(db, "commander_price_tier", candidate)

    if update.commander_sync_interval_minutes is not None:
        if not (1 <= update.commander_sync_interval_minutes <= 1440):
            raise HTTPException(
                status_code=400,
                detail="commander_sync_interval_minutes must be between 1 and 1440",
            )
        _set(db, "commander_sync_interval_minutes", str(update.commander_sync_interval_minutes))

    if update.default_tax_rate_percent is not None:
        if update.default_tax_rate_percent < 0:
            raise HTTPException(status_code=400, detail="default_tax_rate_percent must be >= 0")
        _set(db, "default_tax_rate_percent", str(update.default_tax_rate_percent))

    # ── Branding ──────────────────────────────────────────────────────────
    if update.brand_preset is not None:
        _set(db, "brand_preset", update.brand_preset.strip()[:64])

    for field in ("brand_primary_color", "brand_secondary_color", "brand_accent_color"):
        value = getattr(update, field)
        if value is not None:
            candidate = value.strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", candidate):
                raise HTTPException(status_code=400, detail=f"{field} must be a hex color like #3b82f6")
            _set(db, field, candidate.lower())

    if update.brand_logo_data_url is not None:
        candidate = update.brand_logo_data_url.strip()
        if candidate:
            if not candidate.startswith("data:image/"):
                raise HTTPException(status_code=400, detail="brand_logo_data_url must be a data:image/... URL")
            # ~2.5MB of base64 (~1.8MB actual image) — plenty for a logo,
            # keeps the settings row from growing unreasonably large.
            if len(candidate) > 2_500_000:
                raise HTTPException(status_code=400, detail="Logo image is too large — please use a smaller file (under ~1.5MB)")
        _set(db, "brand_logo_data_url", candidate)

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


@router.post("/settings/commander/test", response_model=CommanderTestOut)
def test_commander_connection(db: Session = Depends(get_db)):
    """
    On-demand check of whatever commander_reader_url is currently saved —
    the UI equivalent of running `curl http://<host>:8200/health` yourself.
    Result is also written to settings so it shows up passively afterward
    without re-testing (poller's own periodic sync updates the same fields,
    so this is just a way to check right now instead of waiting).
    """
    values = _get_all(db)
    base_url = (values.get("commander_reader_url") or "").strip().rstrip("/")
    checked_at = datetime.now(tz=timezone.utc)

    if not base_url:
        raise HTTPException(
            status_code=400,
            detail="No commander_reader_url configured yet — save one below first.",
        )

    connected = False
    error = None
    grades: list[CommanderGradeOut] = []
    try:
        with httpx.Client(timeout=8.0) as client:
            health = client.get(f"{base_url}/health")
            health.raise_for_status()
            connected = health.json().get("connected") is not False
            if connected:
                prices = client.get(f"{base_url}/prices")
                prices.raise_for_status()
                for g in prices.json().get("grades", []):
                    in_effect = g.get("in_effect") or {}
                    grades.append(CommanderGradeOut(
                        id=g.get("id"),
                        name=g.get("name") or f"Grade {g.get('id')}",
                        cash=in_effect.get("cash"),
                        credit=in_effect.get("credit"),
                    ))
            else:
                error = "commander-reader is reachable but reports the Commander itself is unreachable."
    except Exception as exc:
        error = str(exc)

    _set(db, "commander_last_check_at", checked_at.isoformat())
    _set(db, "commander_last_connected", "true" if connected else "false")
    _set(db, "commander_last_error", error or "")

    return CommanderTestOut(
        connected=connected, checked_at=checked_at, error=error,
        grades_count=len(grades) if connected else None, grades=grades,
    )

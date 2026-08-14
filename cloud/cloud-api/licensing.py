"""
License state for the Cloud Utility — the ONLY piece of this codebase that
ever checks a license (see the dev handoff doc's Scope Split section; the
Local Instance never touches any of this).

Two license types, evaluated completely differently:

  - Unlimited: a signed JWT (RS256), verified entirely offline against
    LICENSE_SIGNING_PUBLIC_KEY. No network call, ever, by design — this is
    the sold feature, not a shortcut. Once verified once, status is
    permanently "active" until the file/config is removed.

  - Annual: phone home to the license server (LICENSE_SERVER_URL) on
    startup and every LICENSE_CHECK_INTERVAL_HOURS thereafter. A run of
    failures (unreachable OR the server says "invalid") starts a clock;
    once that clock passes LICENSE_GRACE_DAYS (45, per the dev handoff
    doc), the Cloud Utility enters degraded mode. A single successful
    check clears the clock immediately and restores full functionality —
    "no data loss, immediate restoration" per the spec.

Degraded mode itself (what it actually restricts) lives in auth.py's
require_not_degraded — this module only computes and persists the state.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
import jwt as pyjwt
from sqlalchemy.orm import Session

from database import SessionLocal
from models import CloudLicenseState

logger = logging.getLogger("cloud-api.licensing")

STATE_ID = 1  # single-row table


def _get_or_create_state(db: Session) -> CloudLicenseState:
    state = db.query(CloudLicenseState).filter(CloudLicenseState.id == STATE_ID).first()
    if not state:
        state = CloudLicenseState(id=STATE_ID, status="unconfigured")
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _load_config() -> dict:
    return {
        "type": (os.environ.get("CLOUD_LICENSE_TYPE") or "").strip().lower(),  # "annual" | "unlimited" | ""
        "annual_key": os.environ.get("CLOUD_LICENSE_KEY", "").strip(),
        "license_server_url": os.environ.get("LICENSE_SERVER_URL", "").rstrip("/"),
        "unlimited_file_path": os.environ.get("CLOUD_LICENSE_FILE_PATH", "").strip(),
        "signing_public_key": os.environ.get("LICENSE_SIGNING_PUBLIC_KEY", "").strip(),
        "grace_days": int(os.environ.get("LICENSE_GRACE_DAYS", "45")),
        "check_interval_hours": float(os.environ.get("LICENSE_CHECK_INTERVAL_HOURS", "24")),
    }


def _load_unlimited_token(cfg: dict) -> str:
    """Unlimited license file, inline (CLOUD_LICENSE_FILE) or on disk
    (CLOUD_LICENSE_FILE_PATH) — either works, inline is handier for a small
    env var, a mounted file is handier for a longer JWT."""
    inline = os.environ.get("CLOUD_LICENSE_FILE", "").strip()
    if inline:
        return inline
    path = cfg["unlimited_file_path"]
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return ""


def verify_unlimited(cfg: dict) -> dict:
    """Verify the Unlimited license JWT locally — no network call. Raises on
    failure; caller decides how to record that."""
    token = _load_unlimited_token(cfg)
    if not token:
        raise ValueError("CLOUD_LICENSE_TYPE=unlimited but no license file is configured "
                          "(set CLOUD_LICENSE_FILE or CLOUD_LICENSE_FILE_PATH)")
    if not cfg["signing_public_key"]:
        raise ValueError("LICENSE_SIGNING_PUBLIC_KEY is not configured — cannot verify an Unlimited license offline")
    claims = pyjwt.decode(
        token, cfg["signing_public_key"], algorithms=["RS256"],
        options={"require": ["sub", "iat", "jti"], "verify_exp": False},  # no exp claim on Unlimited licenses, by design
    )
    if claims.get("license_type") != "unlimited":
        raise ValueError("License file is not an Unlimited license (unexpected license_type claim)")
    return claims


def check_annual(cfg: dict) -> dict:
    """Phone home once. Returns the server's response dict; raises on
    network failure (caller treats that the same as an 'invalid' response
    for grace-clock purposes — see the dev handoff doc: 'unreachable OR
    invalid' both count)."""
    if not cfg["annual_key"]:
        raise ValueError("CLOUD_LICENSE_TYPE=annual but CLOUD_LICENSE_KEY is not configured")
    if not cfg["license_server_url"]:
        raise ValueError("LICENSE_SERVER_URL is not configured")
    resp = httpx.post(
        f"{cfg['license_server_url']}/license/check",
        json={"license_key": cfg["annual_key"]},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def run_license_check() -> None:
    """One evaluation cycle — called on startup and on the interval loop
    (main.py). Owns its own DB session since it's called from a background
    task, not a request."""
    db = SessionLocal()
    try:
        cfg = _load_config()
        state = _get_or_create_state(db)
        now = datetime.now(tz=timezone.utc)

        if cfg["type"] == "unlimited":
            try:
                claims = verify_unlimited(cfg)
                state.license_type = "unlimited"
                state.customer_name = claims.get("sub")
                state.station_scope = claims.get("station_scope")
                state.status = "active"
                state.expires_at = None  # no expiry, ever, by design
                state.activated_at = state.activated_at or now
                state.last_check_at = now
                state.last_check_ok = True
                state.last_check_detail = None
                state.failing_since = None
            except Exception as exc:
                # An Unlimited license that fails to verify is a
                # configuration/tampering problem, not a lapse — there's no
                # grace period concept for it (nothing to renew). Surface it
                # as degraded immediately rather than waiting 45 days for a
                # state that will never self-heal without operator action.
                logger.error("Unlimited license verification failed: %s", exc)
                state.license_type = "unlimited"
                state.status = "degraded"
                state.last_check_at = now
                state.last_check_ok = False
                state.last_check_detail = str(exc)

        elif cfg["type"] == "annual":
            try:
                result = check_annual(cfg)
                ok = result.get("status") in ("valid", "grace")
                state.license_type = "annual"
                state.customer_name = result.get("customer_name") or state.customer_name
                state.station_scope = result.get("station_scope") or state.station_scope
                state.expires_at = _parse_dt(result.get("expires_at"))
                state.last_check_at = now
                state.last_check_ok = ok
                state.last_check_detail = result.get("detail")

                if ok:
                    state.status = "active"
                    state.activated_at = state.activated_at or now
                    state.failing_since = None
                else:
                    _apply_failure(state, cfg, now)
            except Exception as exc:
                logger.warning("Annual license phone-home failed (server unreachable?): %s", exc)
                state.license_type = "annual"
                state.last_check_at = now
                state.last_check_ok = False
                state.last_check_detail = f"License server unreachable: {exc}"
                _apply_failure(state, cfg, now)

        else:
            state.status = "unconfigured"
            state.last_check_at = now
            state.last_check_ok = None
            state.last_check_detail = "No CLOUD_LICENSE_TYPE configured"

        state.updated_at = now
        db.commit()
    finally:
        db.close()


def _apply_failure(state: CloudLicenseState, cfg: dict, now: datetime) -> None:
    if state.failing_since is None:
        state.failing_since = now
    failing_since = state.failing_since
    if failing_since.tzinfo is None:
        failing_since = failing_since.replace(tzinfo=timezone.utc)
    days_failing = (now - failing_since).total_seconds() / 86400.0
    state.status = "degraded" if days_failing >= cfg["grace_days"] else "grace"


def _parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) if isinstance(raw, str) else raw
    except Exception:
        return None


def get_state_dict(db: Session) -> dict:
    state = _get_or_create_state(db)
    cfg = _load_config()
    days_remaining_in_grace = None
    if state.status == "grace" and state.failing_since:
        failing_since = state.failing_since
        if failing_since.tzinfo is None:
            failing_since = failing_since.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(tz=timezone.utc) - failing_since).total_seconds() / 86400.0
        days_remaining_in_grace = max(0, round(cfg["grace_days"] - elapsed, 1))
    return {
        "license_type": state.license_type,
        "customer_name": state.customer_name,
        "station_scope": state.station_scope,
        "status": state.status,
        "activated_at": state.activated_at,
        "expires_at": state.expires_at,
        "last_check_at": state.last_check_at,
        "last_check_ok": state.last_check_ok,
        "last_check_detail": state.last_check_detail,
        "grace_days_total": cfg["grace_days"],
        "grace_days_remaining": days_remaining_in_grace,
    }

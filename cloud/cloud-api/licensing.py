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

Two layers of configuration, on purpose:

  - Deployment/infra settings (LICENSE_SERVER_URL, LICENSE_SIGNING_PUBLIC_KEY,
    LICENSE_GRACE_DAYS, LICENSE_CHECK_INTERVAL_HOURS) — env vars only, always.
    These describe *how this deployment is wired up*, not which license it
    holds; there's no reasonable "submit this in a form" story for them.

  - The actual license (type + Annual key, or Unlimited file) —
    CLOUD_LICENSE_TYPE/CLOUD_LICENSE_KEY/CLOUD_LICENSE_FILE(_PATH) env vars
    only SEED this once, on first boot with an empty DB (initial-deployment
    convenience, same pattern as cloud_sync_* on the station side). From
    then on it's stored in CloudLicenseState.configured_* and managed
    entirely through Admin -> License in the cloud frontend (see
    routers/license.py's activate_annual/activate_unlimited/deactivate) —
    no env edits or restarts needed to activate, renew with a new key, or
    switch license types.
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


def _load_infra_config() -> dict:
    """Deployment-level settings — always from env, never from the DB/UI.
    See module docstring."""
    return {
        "license_server_url": os.environ.get("LICENSE_SERVER_URL", "").rstrip("/"),
        "signing_public_key": os.environ.get("LICENSE_SIGNING_PUBLIC_KEY", "").strip(),
        "grace_days": int(os.environ.get("LICENSE_GRACE_DAYS", "45")),
        "check_interval_hours": float(os.environ.get("LICENSE_CHECK_INTERVAL_HOURS", "24")),
    }


def _load_env_seed() -> dict:
    """What the license *credential* would be if seeded purely from env —
    only ever consulted once, by _seed_from_env_once() below, on a
    completely fresh install. Never re-read after that."""
    return {
        "type": (os.environ.get("CLOUD_LICENSE_TYPE") or "").strip().lower(),  # "annual" | "unlimited" | ""
        "annual_key": os.environ.get("CLOUD_LICENSE_KEY", "").strip(),
        "unlimited_file_path": os.environ.get("CLOUD_LICENSE_FILE_PATH", "").strip(),
        "unlimited_file_inline": os.environ.get("CLOUD_LICENSE_FILE", "").strip(),
    }


def _seed_from_env_once(db: Session, state: CloudLicenseState) -> None:
    """First boot only: if nothing has ever been configured via the UI (or a
    previous seed), and env vars describe a license, persist that into
    CloudLicenseState.configured_* so it becomes the durable, live-editable
    source of truth from here on. No-ops instantly on every later boot."""
    if state.configured_type:
        return  # already configured — env vars are never consulted again
    seed = _load_env_seed()
    if seed["type"] not in ("annual", "unlimited"):
        return  # nothing to seed
    if seed["type"] == "annual" and not seed["annual_key"]:
        return
    if seed["type"] == "unlimited":
        token = seed["unlimited_file_inline"] or _read_file(seed["unlimited_file_path"])
        if not token:
            return
        state.configured_unlimited_file = token
    else:
        state.configured_annual_key = seed["annual_key"]
    state.configured_type = seed["type"]
    db.commit()
    logger.info("Seeded license config from env vars (type=%s) — future changes go through Admin -> License, not env.", seed["type"])


def _read_file(path: str) -> str:
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return ""


def _effective_credential(state: CloudLicenseState) -> dict:
    """The license actually configured right now, from the DB — this is
    what run_license_check() and the activate_* validators evaluate."""
    return {
        "type": state.configured_type or "",
        "annual_key": state.configured_annual_key or "",
        "unlimited_token": state.configured_unlimited_file or "",
    }


def verify_unlimited(token: str, infra: dict) -> dict:
    """Verify an Unlimited license JWT locally — no network call. Raises on
    failure; caller decides how to record/report that."""
    if not token:
        raise ValueError("No Unlimited license file is configured.")
    if not infra["signing_public_key"]:
        raise ValueError("LICENSE_SIGNING_PUBLIC_KEY is not configured on this deployment — cannot verify an Unlimited license offline.")
    claims = pyjwt.decode(
        token, infra["signing_public_key"], algorithms=["RS256"],
        options={"require": ["sub", "iat", "jti"], "verify_exp": False},  # no exp claim on Unlimited licenses, by design
    )
    if claims.get("license_type") != "unlimited":
        raise ValueError("That file is not an Unlimited license (unexpected license_type claim).")
    return claims


def check_annual(annual_key: str, infra: dict) -> dict:
    """Phone home once. Returns the server's response dict; raises on
    network failure (caller treats that the same as an 'invalid' response
    for grace-clock purposes — see the dev handoff doc: 'unreachable OR
    invalid' both count)."""
    if not annual_key:
        raise ValueError("No Annual license key is configured.")
    if not infra["license_server_url"]:
        raise ValueError("LICENSE_SERVER_URL is not configured on this deployment.")
    resp = httpx.post(
        f"{infra['license_server_url']}/license/check",
        json={"license_key": annual_key},
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
        state = _get_or_create_state(db)
        _seed_from_env_once(db, state)
        infra = _load_infra_config()
        cred = _effective_credential(state)
        now = datetime.now(tz=timezone.utc)

        if cred["type"] == "unlimited":
            try:
                claims = verify_unlimited(cred["unlimited_token"], infra)
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

        elif cred["type"] == "annual":
            try:
                result = check_annual(cred["annual_key"], infra)
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
                    _apply_failure(state, infra, now)
            except Exception as exc:
                logger.warning("Annual license phone-home failed (server unreachable?): %s", exc)
                state.license_type = "annual"
                state.last_check_at = now
                state.last_check_ok = False
                state.last_check_detail = f"License server unreachable: {exc}"
                _apply_failure(state, infra, now)

        else:
            state.status = "unconfigured"
            state.last_check_at = now
            state.last_check_ok = None
            state.last_check_detail = "No license configured — set one from Admin -> License."

        state.updated_at = now
        db.commit()
    finally:
        db.close()


def _apply_failure(state: CloudLicenseState, infra: dict, now: datetime) -> None:
    if state.failing_since is None:
        state.failing_since = now
    failing_since = state.failing_since
    if failing_since.tzinfo is None:
        failing_since = failing_since.replace(tzinfo=timezone.utc)
    days_failing = (now - failing_since).total_seconds() / 86400.0
    state.status = "degraded" if days_failing >= infra["grace_days"] else "grace"


def _parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) if isinstance(raw, str) else raw
    except Exception:
        return None


def get_state_dict(db: Session) -> dict:
    state = _get_or_create_state(db)
    infra = _load_infra_config()
    days_remaining_in_grace = None
    if state.status == "grace" and state.failing_since:
        failing_since = state.failing_since
        if failing_since.tzinfo is None:
            failing_since = failing_since.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(tz=timezone.utc) - failing_since).total_seconds() / 86400.0
        days_remaining_in_grace = max(0, round(infra["grace_days"] - elapsed, 1))
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
        "grace_days_total": infra["grace_days"],
        "grace_days_remaining": days_remaining_in_grace,
    }


def get_config_dict(db: Session) -> dict:
    """For Admin -> License's activation form — what's currently configured,
    without ever exposing the full secret back to the browser."""
    state = _get_or_create_state(db)
    return {
        "configured_type": state.configured_type,
        "annual_key_hint": (state.configured_annual_key[-4:] if state.configured_annual_key else None),
        "has_unlimited_file": bool(state.configured_unlimited_file),
        "unlimited_customer_name": state.customer_name if state.configured_type == "unlimited" else None,
    }


# ── Activation (Admin -> License in the cloud frontend) ─────────────────────
# Both validate BEFORE persisting — a bad paste fails loudly right away
# instead of silently starting a 45-day degrade clock.

def activate_annual(db: Session, license_key: str) -> dict:
    license_key = (license_key or "").strip()
    if not license_key:
        raise ValueError("License key is required.")
    infra = _load_infra_config()
    result = check_annual(license_key, infra)
    if result.get("status") not in ("valid", "grace"):
        raise ValueError(result.get("detail") or "License server rejected this key.")

    state = _get_or_create_state(db)
    state.configured_type = "annual"
    state.configured_annual_key = license_key
    state.configured_unlimited_file = None
    db.commit()
    run_license_check()
    db.refresh(state)
    return get_state_dict(db)


def activate_unlimited(db: Session, license_file: str) -> dict:
    license_file = (license_file or "").strip()
    if not license_file:
        raise ValueError("License file is required.")
    infra = _load_infra_config()
    verify_unlimited(license_file, infra)  # raises ValueError with a clear message on failure

    state = _get_or_create_state(db)
    state.configured_type = "unlimited"
    state.configured_unlimited_file = license_file
    state.configured_annual_key = None
    db.commit()
    run_license_check()
    db.refresh(state)
    return get_state_dict(db)


def deactivate(db: Session) -> dict:
    state = _get_or_create_state(db)
    state.configured_type = None
    state.configured_annual_key = None
    state.configured_unlimited_file = None
    state.license_type = None
    state.customer_name = None
    state.station_scope = None
    state.status = "unconfigured"
    state.activated_at = None
    state.expires_at = None
    state.failing_since = None
    state.last_check_detail = "Deactivated from Admin -> License."
    state.updated_at = datetime.now(tz=timezone.utc)
    db.commit()
    db.refresh(state)
    return get_state_dict(db)

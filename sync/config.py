"""
Sync service config — deliberately independent of poller/config.py (which
loads tls-decoded.yaml). The sync service doesn't need the tank/network
config at all, only where to push and what to push with.

Env vars here are SEED defaults only, applied once to the `settings` table
the first time the container starts (same pattern poller/main.py already
uses for poll_interval_minutes: env/YAML seeds it, the DB is the live
source of truth from then on). After that first run, cloud sync is fully
configurable live from the local dashboard's Settings panel — no restart,
no env var edits required. This means a station can be set up for cloud
sync two ways:

  1. Set CLOUD_INGEST_URL / STATION_DEVICE_ID / STATION_DEVICE_SECRET in
     .env before first `docker compose up` (see cloud/README.md) — sync
     auto-enables using those values.
  2. Or leave them unset and paste the credential T3 issues directly into
     the dashboard's Settings panel after the fact — same end state.

  DATABASE_URL   — same local Postgres the api/poller use

Optional (all become live-editable `settings` rows after first seed):
  CLOUD_INGEST_URL       — base URL of the cloud hub
  STATION_DEVICE_ID      — issued by an admin in T3 when provisioned
  STATION_DEVICE_SECRET  — issued alongside device_id
  SYNC_INTERVAL_MINUTES  — default push cadence (default: 30)
"""
import os
from dataclasses import dataclass


@dataclass
class SyncConfig:
    database_url: str
    seed_cloud_url: str
    seed_device_id: str
    seed_device_secret: str
    seed_interval_minutes: int
    batch_size: int


def load_config() -> SyncConfig:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    return SyncConfig(
        database_url=database_url,
        seed_cloud_url=os.environ.get("CLOUD_INGEST_URL", "").rstrip("/"),
        seed_device_id=os.environ.get("STATION_DEVICE_ID", ""),
        seed_device_secret=os.environ.get("STATION_DEVICE_SECRET", ""),
        seed_interval_minutes=int(os.environ.get("SYNC_INTERVAL_MINUTES", "30")),
        batch_size=int(os.environ.get("SYNC_BATCH_SIZE", "500")),
    )

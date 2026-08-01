"""
Remote uploader stub.

When remote.enabled=true, POSTs readings/deliveries to the central server
using the hex-32 device_id as authentication.
Currently a no-op stub — wired but inactive.
"""

import logging
from typing import Optional

import httpx

from config import RemoteConfig
from models import DeliveryEvent, TankReading

logger = logging.getLogger(__name__)


class RemoteUploader:
    def __init__(self, cfg: RemoteConfig):
        self._cfg = cfg
        self._client: Optional[httpx.Client] = None

        if cfg.enabled:
            if not cfg.device_id or len(cfg.device_id) != 32:
                logger.warning(
                    "Remote enabled but device_id is missing or not 32 hex chars — disabled."
                )
                self._enabled = False
            else:
                self._enabled = True
                self._client = httpx.Client(
                    base_url=cfg.server_url,
                    headers={"X-Device-ID": cfg.device_id, "Content-Type": "application/json"},
                    timeout=10.0,
                )
                logger.info("Remote uploader initialized for %s", cfg.server_url)
        else:
            self._enabled = False

    def upload_readings(self, readings: list[TankReading]) -> None:
        if not self._enabled or not self._client:
            return
        try:
            payload = [
                {
                    "tank_id": r.tank_id,
                    "polled_at": r.polled_at.isoformat(),
                    "volume_gallons": r.volume_gallons,
                    "ullage_gallons": r.ullage_gallons,
                    "height_inches": r.height_inches,
                    "water_inches": r.water_inches,
                    "temperature_f": r.temperature_f,
                }
                for r in readings
            ]
            resp = self._client.post("/ingest/readings", json=payload)
            resp.raise_for_status()
            logger.debug("Uploaded %d readings to remote server", len(readings))
        except Exception as exc:
            logger.warning("Remote readings upload failed: %s", exc)

    def upload_delivery(self, event: DeliveryEvent) -> None:
        if not self._enabled or not self._client:
            return
        try:
            payload = {
                "tank_id": event.tank_id,
                "detected_at": event.detected_at.isoformat(),
                "start_volume_gallons": event.start_volume_gallons,
                "end_volume_gallons": event.end_volume_gallons,
                "gallons_received": event.gallons_received,
            }
            resp = self._client.post("/ingest/deliveries", json=payload)
            resp.raise_for_status()
            logger.debug("Uploaded delivery (tank %d +%.0f gal)", event.tank_id, event.gallons_received)
        except Exception as exc:
            logger.warning("Remote delivery upload failed: %s", exc)

    def close(self) -> None:
        if self._client:
            self._client.close()

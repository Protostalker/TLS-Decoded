"""
Mock driver — same interface as TLSNetworkDriver, no hardware needed.

Simulates three tanks starting at 75% capacity, draining at ~50 gal/hr each.
Tank 1 gets a delivery on every 5th poll (jumps to 95%).
Set network.mock = true in tls-decoded.yaml to use this instead of live hardware.
"""

import logging
import random
import time
from datetime import datetime
from typing import Optional

from config import AppConfig
from models import TankReading

logger = logging.getLogger(__name__)


class MockDriver:
    def __init__(self, cfg: AppConfig) -> None:
        self._tanks_cfg = {t.id: t for t in cfg.tanks}
        self._poll_count = 0
        self._last_poll_time: Optional[float] = None
        self._volumes: dict[int, float] = {
            t.id: t.capacity_gallons * 0.75 for t in cfg.tanks
        }

    def poll_inventory(self, polled_at: datetime) -> list[TankReading]:
        self._advance_time()
        self._poll_count += 1
        readings: list[TankReading] = []

        for tank_id, tank_cfg in sorted(self._tanks_cfg.items()):
            vol = self._volumes[tank_id]
            capacity = tank_cfg.capacity_gallons

            if self._poll_count % 5 == 0 and tank_id == 1:
                old_vol = vol
                vol = capacity * 0.95
                logger.info("[MOCK] Delivery tank %d: %.0f → %.0f gal", tank_id, old_vol, vol)
                self._volumes[tank_id] = vol

            ullage = max(0.0, capacity - vol)
            height_in = (vol / capacity * 120.0) if capacity else 0.0

            readings.append(TankReading(
                tank_id=tank_id,
                polled_at=polled_at,
                volume_gallons=round(vol, 1),
                ullage_gallons=round(ullage, 1),
                height_inches=round(height_in, 2),
                water_inches=0.0,
                temperature_f=round(random.uniform(75.0, 90.0), 1),
            ))

        return readings

    def close(self) -> None:
        pass

    def _advance_time(self) -> None:
        now = time.monotonic()
        if self._last_poll_time is None:
            elapsed_hours = 1.0
        else:
            elapsed_hours = min((now - self._last_poll_time) / 3600.0, 2.0)
        self._last_poll_time = now

        for tank_id in self._tanks_cfg:
            drain = 50.0 * elapsed_hours + random.uniform(-2.0, 2.0)
            self._volumes[tank_id] = max(0.0, self._volumes[tank_id] - drain)

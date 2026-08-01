"""Data structures — exactly what the TLS-350 display format provides."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TankReading:
    tank_id: int
    polled_at: datetime
    volume_gallons: float
    ullage_gallons: float
    height_inches: float
    water_inches: float
    temperature_f: float


@dataclass
class DeliveryEvent:
    tank_id: int
    detected_at: datetime
    start_volume_gallons: float
    end_volume_gallons: float
    gallons_received: float
    # Net + estimated concurrent sales during the delivery window, in case fuel
    # was being dispensed at the same time it was delivered (see
    # Poller._confirm_deliveries). None until a confirmation pass has run.
    adjusted_gallons_received: Optional[float] = None
    confirmed: bool = False
    # When this jump was first detected (before confirmation extended
    # detected_at forward to the settled time) — the true anchor for a
    # delivery session, preserved across poll-to-poll merges.
    session_started_at: Optional[datetime] = None
    # How many separate poll-to-poll increases have been folded into this
    # session (see Poller._merge_or_persist_delivery).
    merged_poll_count: int = 1


@dataclass
class PollResult:
    polled_at: datetime
    success: bool
    duration_ms: int
    readings: list[TankReading] = field(default_factory=list)
    error_message: Optional[str] = None

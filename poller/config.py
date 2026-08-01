"""Load and validate tls-decoded.yaml configuration."""
import os
from dataclasses import dataclass
from typing import Optional
import yaml


@dataclass
class TankConfig:
    id: int
    name: str
    capacity_gallons: float
    product: str
    reorder_threshold_gallons: float


@dataclass
class NetworkConfig:
    host: str
    port: int
    timeout_seconds: float
    mock: bool


@dataclass
class PollingConfig:
    mode: str  # "interval" or "schedule"
    interval_minutes: int
    schedule_times: list[str]
    query_alarms: bool
    query_deliveries: bool


@dataclass
class AnalyticsConfig:
    consumption_window_hours: int
    delivery_detection_jump_gallons: float


@dataclass
class RemoteConfig:
    enabled: bool
    server_url: str
    device_id: str


@dataclass
class AppConfig:
    station_name: str
    tanks: list[TankConfig]
    network: NetworkConfig
    polling: PollingConfig
    analytics: AnalyticsConfig
    remote: RemoteConfig


def load_config(path: str = "/app/config/tls-decoded.yaml") -> AppConfig:
    path = os.environ.get("CONFIG_PATH", path)

    with open(path) as f:
        raw = yaml.safe_load(f)

    tanks = [
        TankConfig(
            id=t["id"],
            name=t["name"],
            capacity_gallons=float(t["capacity_gallons"]),
            product=t.get("product", ""),
            reorder_threshold_gallons=float(t.get("reorder_threshold_gallons", 0)),
        )
        for t in raw["station"]["tanks"]
    ]

    net_raw = raw["network"]
    network = NetworkConfig(
        host=os.environ.get("TLS_HOST", str(net_raw["host"])),
        port=int(os.environ.get("TLS_PORT", net_raw.get("port", 5000))),
        timeout_seconds=float(net_raw.get("timeout_seconds", 5)),
        mock=bool(net_raw.get("mock", False)),
    )

    polling_raw = raw["polling"]
    polling = PollingConfig(
        mode=polling_raw.get("mode", "interval"),
        interval_minutes=int(polling_raw.get("interval_minutes", 60)),
        schedule_times=polling_raw.get("schedule_times", []),
        query_alarms=bool(polling_raw.get("query_alarms", True)),
        query_deliveries=bool(polling_raw.get("query_deliveries", True)),
    )

    analytics_raw = raw.get("analytics", {})
    analytics = AnalyticsConfig(
        consumption_window_hours=int(analytics_raw.get("consumption_window_hours", 168)),
        delivery_detection_jump_gallons=float(
            analytics_raw.get("delivery_detection_jump_gallons", 200)
        ),
    )

    remote_raw = raw.get("remote", {})
    remote = RemoteConfig(
        enabled=bool(remote_raw.get("enabled", False)),
        server_url=str(remote_raw.get("server_url", "")),
        device_id=str(remote_raw.get("device_id", "")),
    )

    return AppConfig(
        station_name=raw["station"]["name"],
        tanks=tanks,
        network=network,
        polling=polling,
        analytics=analytics,
        remote=remote,
    )

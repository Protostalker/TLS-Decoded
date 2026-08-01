"""
TLS-350 RS-232 serial driver.

Protocol:
  Command:  SOH + function_code  (e.g. b'\x01i20100')
  Response: SOH + func_code + YYMMDDHHmm + data + '&&' + 4-hex-checksum + ETX

Function codes used:
  i20100  – inventory all tanks
  i10100  – all active alarms
  i20200  – delivery report
"""

import logging
import struct
import time
from datetime import datetime
from typing import Optional

import serial

from config import AppConfig, SerialConfig
from models import AlarmRecord, TankReading

logger = logging.getLogger(__name__)

SOH = b"\x01"
ETX = b"\x03"


# ── Checksum ──────────────────────────────────────────────────────────────────

def verify_checksum(message: bytes) -> bool:
    """Verify Veeder-Root 4-hex checksum appended after '&&'."""
    idx = message.rfind(b"&&")
    if idx == -1 or len(message) < idx + 6:
        return False
    payload = message[: idx + 2]
    try:
        checksum = int(message[idx + 2 : idx + 6], 16)
    except ValueError:
        return False
    total = sum(b & 0x7F for b in payload) + checksum
    return (total & 0xFFFF) == 0


# ── Float parsing ─────────────────────────────────────────────────────────────

def parse_vr_float(hex8: str) -> float:
    """Decode an 8-char ASCII hex string as big-endian IEEE-754 float."""
    if hex8 == "00000000":
        return 0.0
    try:
        return struct.unpack(">f", bytes.fromhex(hex8))[0]
    except (ValueError, struct.error):
        return 0.0


# ── Response parser ───────────────────────────────────────────────────────────

def _strip_envelope(raw: bytes) -> Optional[bytes]:
    """Strip SOH, function echo, timestamp, && checksum, and ETX; return payload."""
    try:
        start = raw.index(SOH)
    except ValueError:
        return None
    # Skip SOH + 6-char func code + 10-char timestamp = 17 bytes from SOH
    payload_start = start + 17
    end = raw.rfind(b"&&")
    if end == -1:
        return None
    return raw[payload_start:end]


def parse_i201_response(raw: bytes, polled_at: datetime) -> list[TankReading]:
    """Parse i20100 (all-tank inventory) response into TankReading list."""
    if not verify_checksum(raw):
        logger.warning("i20100 checksum verification failed")

    payload = _strip_envelope(raw)
    if not payload:
        logger.error("Could not strip i201 response envelope")
        return []

    text = payload.decode("ascii", errors="replace").strip()
    readings: list[TankReading] = []
    pos = 0

    while pos < len(text):
        # Need at least 2-char tank number
        if pos + 2 > len(text):
            break

        try:
            tank_id = int(text[pos : pos + 2])
        except ValueError:
            break
        pos += 2

        if pos >= len(text):
            break
        _product_code = text[pos]  # single char product code
        pos += 1

        if pos + 4 > len(text):
            break
        status_hex = text[pos : pos + 4]
        pos += 4
        try:
            status_bits = int(status_hex, 16)
        except ValueError:
            status_bits = 0
        delivery_in_progress = bool(status_bits & 0x01)
        leak_test_running = bool(status_bits & 0x02)

        if pos + 2 > len(text):
            break
        try:
            field_count = int(text[pos : pos + 2], 16)
        except ValueError:
            break
        pos += 2

        floats: list[float] = []
        for _ in range(field_count):
            if pos + 8 > len(text):
                break
            floats.append(parse_vr_float(text[pos : pos + 8]))
            pos += 8

        # Field order: volume, tc_volume, ullage, height, water, temperature, water_volume
        def _f(i: int) -> float:
            return floats[i] if i < len(floats) else 0.0

        readings.append(
            TankReading(
                tank_id=tank_id,
                polled_at=polled_at,
                volume_gallons=_f(0),
                tc_volume_gallons=_f(1),
                ullage_gallons=_f(2),
                height_inches=_f(3),
                water_inches=_f(4),
                temperature_f=_f(5),
                water_volume_gallons=_f(6),
                delivery_in_progress=delivery_in_progress,
                leak_test_running=leak_test_running,
            )
        )

    return readings


_ALARM_DESCRIPTIONS = {
    (2, 2): "Leak",
    (2, 3): "High Water",
    (2, 4): "Overfill",
    (2, 5): "Low Product",
    (2, 6): "Sudden Loss",
    (1, 0): "System Alarm",
    (3, 0): "Liquid Sensor Alarm",
    (6, 0): "Volumetric Line Leak",
}

_CATEGORY_NAMES = {
    0: "All Normal",
    1: "System Alarm",
    2: "Tank Alarm",
    3: "Liquid Sensor Alarm",
    6: "Volumetric Line Leak",
}


def parse_i101_response(raw: bytes, detected_at: datetime) -> list[AlarmRecord]:
    """Parse i10100 (all active alarms) response."""
    if not verify_checksum(raw):
        logger.warning("i10100 checksum verification failed")

    payload = _strip_envelope(raw)
    if not payload:
        return []

    text = payload.decode("ascii", errors="replace").strip()
    if not text or text.startswith("00"):
        return []  # 00 = All Normal

    alarms: list[AlarmRecord] = []
    pos = 0

    while pos + 4 <= len(text):
        try:
            category_code = int(text[pos : pos + 2])
            alarm_code = int(text[pos + 2 : pos + 4])
        except ValueError:
            break
        pos += 4

        tank_id: Optional[int] = None
        if pos + 2 <= len(text):
            try:
                tank_id = int(text[pos : pos + 2])
                pos += 2
            except ValueError:
                pass

        desc = _ALARM_DESCRIPTIONS.get(
            (category_code, alarm_code),
            _CATEGORY_NAMES.get(category_code, f"Alarm {category_code}/{alarm_code}"),
        )

        alarms.append(
            AlarmRecord(
                tank_id=tank_id,
                detected_at=detected_at,
                category_code=category_code,
                alarm_code=alarm_code,
                description=desc,
            )
        )

    return alarms


# ── Serial driver class ───────────────────────────────────────────────────────

class TLSSerialDriver:
    """Manages a serial connection to a Veeder-Root TLS-350."""

    def __init__(self, cfg: SerialConfig):
        self._cfg = cfg
        self._port: Optional[serial.Serial] = None

    def connect(self) -> None:
        """Open the serial port, retry until available."""
        parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
        while True:
            try:
                self._port = serial.Serial(
                    port=self._cfg.port,
                    baudrate=self._cfg.baudrate,
                    bytesize=self._cfg.databits,
                    parity=parity_map.get(self._cfg.parity, serial.PARITY_NONE),
                    stopbits=self._cfg.stopbits,
                    timeout=self._cfg.timeout_seconds,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                )
                logger.info("Serial port %s opened", self._cfg.port)
                return
            except serial.SerialException as exc:
                logger.warning("Cannot open %s: %s — retrying in 10s", self._cfg.port, exc)
                time.sleep(10)

    def _send_command(self, func_code: str) -> bytes:
        """Send a TLS function command and read the full response."""
        if self._port is None or not self._port.is_open:
            self.connect()

        cmd = SOH + func_code.encode("ascii")
        assert self._port is not None
        self._port.reset_input_buffer()
        self._port.write(cmd)

        # Read until ETX or timeout
        buf = bytearray()
        deadline = time.monotonic() + max(self._cfg.timeout_seconds, 5)
        while time.monotonic() < deadline:
            chunk = self._port.read(256)
            if chunk:
                buf.extend(chunk)
                if ETX in buf:
                    break
        return bytes(buf)

    def _reconnect(self) -> None:
        if self._port:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
        time.sleep(2)
        self.connect()

    def poll_inventory(self, polled_at: datetime) -> list[TankReading]:
        for attempt in range(3):
            try:
                raw = self._send_command("i20100")
                if not raw:
                    raise IOError("Empty response from TLS-350")
                return parse_i201_response(raw, polled_at)
            except (serial.SerialException, IOError) as exc:
                logger.warning("Inventory poll attempt %d failed: %s", attempt + 1, exc)
                self._reconnect()
        logger.error("All inventory poll attempts failed")
        return []

    def poll_alarms(self, detected_at: datetime) -> list[AlarmRecord]:
        for attempt in range(3):
            try:
                raw = self._send_command("i10100")
                if not raw:
                    raise IOError("Empty response from TLS-350")
                return parse_i101_response(raw, detected_at)
            except (serial.SerialException, IOError) as exc:
                logger.warning("Alarm poll attempt %d failed: %s", attempt + 1, exc)
                self._reconnect()
        logger.error("All alarm poll attempts failed")
        return []

    def close(self) -> None:
        if self._port and self._port.is_open:
            self._port.close()

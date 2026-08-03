"""
TLS-350 network driver.

Connects to a StarTech (or similar) serial-to-Ethernet adapter in TCP Server mode.
The adapter passes raw bytes straight through to the TLS-350.

Connection: TCP to 192.168.0.250:5000
  (set a DHCP reservation for MAC E8-EA-6A-B4-07-51 so the IP stays fixed)

Command format  : SOH (0x01) + 3-digit numeric code
                  b'\\x01200'  → all tanks inventory
                  b'\\x01201'  → tank 1 only
                  b'\\x01202'  → tank 2 only
                  b'\\x01203'  → tank 3 only

Response format : ASCII display text ending with ETX (0x03)
  e.g.
    200
    881283 SM SERVICE ST
    16435 S. FIGUEROA ST
    GARDENA CA 90248
    310 532-5663
    JUL 31, 2026  6:12 PM
    TANK  PRODUCT               GALLONS  INCHES   WATER  DEG F   ULLAGE
      1   UNLEADED                 4175   36.12     0.0   86.8     7857
      2   SUPER                    1394   16.61     0.0   83.2    10369
      3   DIESEL                   3960   34.72     0.0   81.8     8072

Fields we get: volume_gallons, ullage_gallons, height_inches, water_inches, temperature_f
"""

import logging
import re
import socket
import time
from datetime import datetime
from typing import Optional

from config import NetworkConfig
from models import TankReading

logger = logging.getLogger(__name__)

SOH = b"\x01"
ETX = b"\x03"

# Matches a tank data row: 1-4 leading spaces, 1-2 digit tank number, then a space.
# e.g. "  1   UNLEADED   4175 ..."
_DATA_ROW_RE = re.compile(r'^\s{1,4}(\d{1,2})\s')


class TLSNetworkDriver:
    """TCP client for TLS-350 via serial-to-Ethernet adapter."""

    def __init__(self, cfg: NetworkConfig) -> None:
        self._host = cfg.host
        self._port = cfg.port
        self._timeout = cfg.timeout_seconds
        self._sock: Optional[socket.socket] = None

    # ── Connection management ─────────────────────────────────────────────────

    def _connect(self) -> None:
        """Open TCP connection with 3 retries and exponential backoff."""
        for attempt in range(3):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self._timeout)
                s.connect((self._host, self._port))
                self._sock = s
                logger.info("Connected to TLS-350 at %s:%d", self._host, self._port)
                return
            except OSError as exc:
                wait = 0.5 * (2 ** attempt)  # 0.5 s, 1 s, 2 s
                logger.warning(
                    "TCP connect attempt %d/3 to %s:%d failed: %s — retrying in %.1fs",
                    attempt + 1, self._host, self._port, exc, wait,
                )
                time.sleep(wait)
        raise ConnectionError(
            f"Cannot connect to TLS-350 at {self._host}:{self._port} after 3 attempts"
        )

    def _ensure_connected(self) -> socket.socket:
        if self._sock is not None:
            try:
                self._sock.getpeername()
                return self._sock
            except OSError:
                self._close()
        self._connect()
        assert self._sock is not None
        return self._sock

    def _close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def close(self) -> None:
        self._close()

    # ── Low-level I/O ─────────────────────────────────────────────────────────

    def _send_command(self, code: str) -> str:
        """
        Send SOH + 3-digit code, read until ETX.
        Retries up to 3 times on socket errors, reconnecting between attempts.
        Returns the full response as a decoded string.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                sock = self._ensure_connected()

                # Drain any stale bytes
                sock.setblocking(False)
                try:
                    while sock.recv(4096):
                        pass
                except (BlockingIOError, OSError):
                    pass
                sock.setblocking(True)
                sock.settimeout(self._timeout)

                cmd = SOH + code.encode("ascii")
                logger.debug("→ %r", cmd)
                sock.sendall(cmd)

                buf = bytearray()
                deadline = time.monotonic() + max(self._timeout, 8.0)
                while time.monotonic() < deadline:
                    try:
                        chunk = sock.recv(1024)
                    except socket.timeout:
                        break
                    if not chunk:
                        raise ConnectionError("Remote closed connection mid-read")
                    buf.extend(chunk)
                    if ETX[0] in buf:
                        break

                raw = buf.decode("ascii", errors="replace")
                logger.debug("← %d bytes", len(buf))
                return raw

            except (OSError, ConnectionError) as exc:
                last_exc = exc
                logger.warning("Command %s attempt %d/3 failed: %s", code, attempt + 1, exc)
                self._close()
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))

        raise IOError(
            f"Could not reach the adapter at {self._host}:{self._port} after 3 attempts "
            f"for command '{code}' — last error: {last_exc}"
        )

    # ── Public poll interface ─────────────────────────────────────────────────

    def poll_inventory(self, polled_at: datetime) -> list[TankReading]:
        """Send \\x01200 and parse the display-format inventory table."""
        raw = self._send_command("200")

        if not raw:
            wait_s = max(self._timeout, 8.0)
            raise IOError(
                f"TCP connection to {self._host}:{self._port} is fine, but got 0 bytes "
                f"back after sending command 200 (waited {wait_s:.0f}s). The network "
                "link to the adapter is OK — this points at the serial side: wrong "
                "null-modem vs. straight-through cable (TX/RX swapped), a missing "
                "signal ground, or a baud/parity mismatch between the adapter and "
                "the TLS-350."
            )

        readings = _parse_inventory_display(raw, polled_at)
        if not readings:
            snippet = raw.strip().replace("\n", " | ")[:200]
            raise IOError(
                f"Got {len(raw)} bytes back from the gauge but couldn't find any "
                f"tank rows in it — check the adapter's serial baud rate/parity "
                f"settings, or the gauge may be reporting its own error. Raw "
                f"response started with: {snippet!r}"
            )
        return readings


# ── Display-format parser ─────────────────────────────────────────────────────

def _parse_inventory_display(text: str, polled_at: datetime) -> list[TankReading]:
    """
    Parse inventory table from a \\x01200 response.

    Data rows are identified by 1-4 leading spaces + 1-2 digit tank number.
    The last 5 whitespace-delimited tokens on each row are:
        GALLONS  INCHES  WATER  DEG_F  ULLAGE

    Station header lines (command echo, address, timestamp, column headers)
    have no leading spaces or start with letters, so they are naturally skipped.
    """
    readings: list[TankReading] = []

    for line in text.splitlines():
        if not _DATA_ROW_RE.match(line):
            continue
        tokens = line.split()
        if len(tokens) < 6:
            continue
        try:
            tank_id = int(tokens[0])
            volume  = float(tokens[-5].replace(",", ""))
            height  = float(tokens[-4].replace(",", ""))
            water   = float(tokens[-3].replace(",", ""))
            temp    = float(tokens[-2].replace(",", ""))
            ullage  = float(tokens[-1].replace(",", ""))
        except (ValueError, IndexError) as exc:
            logger.debug("Skipping unparseable row %r: %s", line, exc)
            continue

        readings.append(TankReading(
            tank_id=tank_id,
            polled_at=polled_at,
            volume_gallons=volume,
            ullage_gallons=ullage,
            height_inches=height,
            water_inches=water,
            temperature_f=temp,
        ))

    if readings:
        logger.info(
            "Parsed %d tank readings: %s",
            len(readings),
            {r.tank_id: f"{r.volume_gallons:.0f} gal" for r in readings},
        )
    return readings

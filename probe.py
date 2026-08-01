"""
TLS-350 command probe — run this on any machine on the 192.168.0.x network.

Usage:
    python probe.py

Sweeps 3-digit command codes and prints the raw response.
Known working: 200 (all tanks), 201/202/203 (per tank).
"""

import socket
import time

HOST = "192.168.0.250"
PORT = 5000
TIMEOUT = 6  # seconds to wait for ETX


def query(code: str) -> str:
    try:
        with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as s:
            s.sendall(b"\x01" + code.encode())
            buf = bytearray()
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline:
                try:
                    chunk = s.recv(1024)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
                if 0x03 in buf:
                    break
            if not buf:
                return "(no response)"
            return buf.decode("ascii", errors="replace").strip("\x01\x03").strip()
    except Exception as e:
        return f"ERROR: {e}"


# Codes to probe, grouped by likely category
PROBE_CODES = [
    # Inventory (200 confirmed)
    ("200", "All-tank inventory [CONFIRMED]"),
    ("201", "Tank 1 inventory [CONFIRMED]"),
    ("202", "Tank 2 inventory [CONFIRMED]"),
    ("203", "Tank 3 inventory"),

    # Alarms / status
    ("100", "Alarm status — all tanks"),
    ("101", "Alarm status — tank 1"),

    # Deliveries / reconciliation
    ("300", "Delivery report"),
    ("301", "Delivery — tank 1"),
    ("302", "Delivery — tank 2"),
    ("303", "Delivery — tank 3"),
    ("400", "Reconciliation / shift report"),

    # Sensors / probes
    ("500", "Sensor / probe status"),
    ("501", "Sensor — tank 1"),

    # System info
    ("001", "System date / time"),
    ("002", "Software version"),
    ("003", "Station / setup info"),
    ("010", "System status"),
]


OUTPUT_FILE = "probe_output.txt"


def main():
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out(f"Probing TLS-350 at {HOST}:{PORT}\n")
    for code, label in PROBE_CODES:
        out("─" * 60)
        out(f"\\x01{code}  —  {label}")
        resp = query(code)
        out(resp[:800] + ("…" if len(resp) > 800 else ""))
        out()
        time.sleep(0.75)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

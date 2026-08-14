#!/usr/bin/env python3
"""
TLS-Decoded Local Instance — software update checker/applier.

Runs on the HOST (via cron / systemd timer / Windows Task Scheduler — see
README.md), NOT inside a container. That's a deliberate choice, not an
oversight: this script needs to run `git pull` and `docker compose up -d
--build` against the real repo checkout, and doing that from inside a
sibling container over the Docker socket runs into a well-known problem —
docker compose resolves the compose file's relative bind-mount paths (e.g.
`./config:/app/config:ro`) against whatever path the CLI is invoked from,
but the daemon it's actually talking to (via the mounted socket) needs
those paths to resolve on the HOST's filesystem, which only lines up if the
container's mount point is bind-mounted to the exact same path as the host
repo — fragile, and more machinery than this MVP needs (see the dev
handoff doc's section 3.3: "don't over-build this initially"). A plain
host-level script sidesteps the whole problem, and it's a natural extension
of the update.sh/update.bat scripts that already exist and already work
this way.

What it does, once per invocation:
  1. Ask the local API (http://localhost:${API_PORT}/api/settings) whether
     update checking is enabled, and whether a check is due (interval
     elapsed, or a check-now request is pending — see api/routers/settings.py's
     update_check_pending, which is also how a Cloud Utility "check for
     updates now" click reaches this station: cloud -> sync container ->
     local setting flag -> this script, never an inbound connection).
  2. If due: `git fetch`, compare local HEAD to the tracking branch's
     remote HEAD. If they differ: `git pull` then `docker compose up -d
     --build`. If they're already the same, skip the rebuild (no point
     restarting healthy containers for a no-op pull) but still record that
     a check happened.
  3. Report the outcome back to the local API (POST /api/settings/update/report)
     so the dashboard's Settings -> Software Updates panel has something to show.

Runs once and exits — safe to invoke every hour from cron/Task Scheduler;
it no-ops quickly if a check isn't due yet. See README.md for how to wire
that up, and for the "opt-in, disclosed on first run" requirement this is
built around (update_check_enabled defaults to false — this script is a
no-op until an operator turns it on from Settings).

No third-party dependencies on purpose — just stdlib — so it runs with
whatever python3 is already on the box.
"""
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] check_for_updates: %(message)s")
logger = logging.getLogger("check_for_updates")

API_URL = os.environ.get("LOCAL_API_URL", "http://localhost:8000").rstrip("/")
REPO_PATH = os.environ.get("REPO_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TIMEOUT = 20


def _api_get(path: str) -> dict:
    with urllib.request.urlopen(f"{API_URL}{path}", timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def _api_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API_URL}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def _run(cmd: list[str]) -> tuple[int, str]:
    logger.info("$ %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True, timeout=900)
    except FileNotFoundError as exc:
        return 127, f"{cmd[0]}: command not found ({exc})"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd)}: timed out"
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def _current_ref() -> str:
    code, out = _run(["git", "rev-parse", "--short", "HEAD"])
    return out.strip() if code == 0 else "unknown"


def _interval_elapsed(last_checked_at: str | None, interval_days: int) -> bool:
    if not last_checked_at:
        return True
    try:
        last = datetime.fromisoformat(last_checked_at)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (datetime.now(tz=timezone.utc) - last).days >= interval_days


def main() -> int:
    try:
        settings = _api_get("/api/settings")
    except (urllib.error.URLError, OSError) as exc:
        logger.error("Could not reach the local API at %s — is the station stack up? (%s)", API_URL, exc)
        return 1

    if not settings.get("update_check_enabled"):
        logger.info("Update checking is disabled (Settings -> Software Updates) — nothing to do.")
        return 0

    pending_request = bool(settings.get("update_check_pending"))
    due = pending_request or _interval_elapsed(settings.get("update_last_checked_at"), settings.get("update_check_interval_days", 7))

    if not due:
        logger.info("Not due yet (interval=%sd, last checked %s).",
                     settings.get("update_check_interval_days"), settings.get("update_last_checked_at") or "never")
        return 0

    logger.info("Checking for updates%s…", " (requested now)" if pending_request else "")

    code, out = _run(["git", "fetch", "--quiet"])
    if code != 0:
        logger.error("git fetch failed: %s", out)
        _report(applied=False, result=f"git fetch failed: {out[:300]}")
        return 1

    code, local_head = _run(["git", "rev-parse", "HEAD"])
    code2, remote_head = _run(["git", "rev-parse", "@{u}"])
    if code != 0 or code2 != 0:
        logger.error("Could not determine local/remote HEAD (is this a git checkout with a tracking branch?)")
        _report(applied=False, result="Could not determine local/remote HEAD")
        return 1

    if local_head == remote_head:
        logger.info("Already up to date (%s).", _current_ref())
        _report(applied=False, result="Already up to date")
        return 0

    logger.info("Update available — pulling and rebuilding…")
    code, out = _run(["git", "pull"])
    if code != 0:
        logger.error("git pull failed: %s", out)
        _report(applied=False, result=f"git pull failed: {out[:300]}")
        return 1

    code, out = _run(["docker", "compose", "up", "-d", "--build"])
    if code != 0:
        logger.error("docker compose up failed: %s", out)
        _report(applied=False, result=f"Pulled to {_current_ref()} but rebuild failed: {out[:300]}")
        return 1

    ref = _current_ref()
    logger.info("Updated and rebuilt successfully — now at %s.", ref)
    _report(applied=True, result=f"Updated to {ref}")
    return 0


def _report(applied: bool, result: str) -> None:
    try:
        _api_post("/api/settings/update/report", {"applied": applied, "current_ref": _current_ref(), "result": result})
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("Update check completed but could not report the result back to the local API: %s", exc)


if __name__ == "__main__":
    sys.exit(main())

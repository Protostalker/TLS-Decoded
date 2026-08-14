# Software updates (Local Instance)

Per the dev handoff doc's Update Mechanism section: a pull model, opt-in,
and completely independent of licensing (there is no license on this side
— the Local Instance never checks one, and update-checking must work the
same whether or not the operator has any relationship with the Cloud
Utility at all).

## How it works

1. `check_for_updates.py` runs **on the host** (not in a container — see
   the big comment at the top of that file for why: doing `docker compose
   up -d --build` from inside a sibling container over the Docker socket
   runs into a well-known bind-mount-path problem that isn't worth solving
   for a v1). It's stdlib-only, so it runs with whatever `python3` is
   already on the box next to `docker`/`git`.
2. It asks the local API (`GET /api/settings`) whether update-checking is
   enabled and due, `git fetch`s, compares local vs. remote HEAD, and if
   they differ: `git pull` + `docker compose up -d --build`. It reports the
   outcome back (`POST /api/settings/update/report`) so Settings ->
   Software Updates has something to show.
3. **Off by default.** Turn it on from the local dashboard's Settings page
   (`update_check_enabled`), or by clicking "Check for updates now" once
   (which also flips it on... no — it doesn't; the check-now button
   no-ops if the feature is off, by design, so a stray click can't
   silently enable auto-updates). See `api/routers/settings.py`.
4. A Cloud Utility admin can also trigger a check remotely (per-station
   "Check for updates now" button, if the station has cloud sync
   configured) — this **only sets a flag** the station's own `sync`
   container picks up on its normal poll (never an inbound connection into
   the station's network); the station still only checks/applies if it
   has update-checking enabled locally. See `cloud/cloud-api/routers/admin.py`'s
   `request_update_check` and `sync/main.py`'s `apply_pending_update_check_request`.

## Setting up the recurring check

Pick whichever fits the box this station runs on. All of these just run
`check_for_updates.py` once; the script itself decides whether a check is
actually due (based on `update_check_interval_days`, default 7) or
requested (the check-now flag) — safe to invoke more often than that.

### Linux (cron)

```
# Check hourly; the script no-ops unless a check is actually due/requested.
0 * * * * cd /path/to/tls-decoded && /usr/bin/python3 updater/check_for_updates.py >> /var/log/tls-decoded-updater.log 2>&1
```

### Linux (systemd timer) — preferred if available

```ini
# /etc/systemd/system/tls-decoded-updater.service
[Unit]
Description=TLS-Decoded update checker

[Service]
Type=oneshot
WorkingDirectory=/path/to/tls-decoded
ExecStart=/usr/bin/python3 updater/check_for_updates.py
```

```ini
# /etc/systemd/system/tls-decoded-updater.timer
[Unit]
Description=Run the TLS-Decoded update checker hourly

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now tls-decoded-updater.timer
```

### Windows (Task Scheduler)

Create a scheduled task that runs hourly:

```
schtasks /create /tn "TLS-Decoded Updater" /tr "python C:\path\to\tls-decoded\updater\check_for_updates.py" /sc hourly /ru SYSTEM
```

## Env vars

- `LOCAL_API_URL` — default `http://localhost:8000`. Only needs changing if
  `API_PORT` was customized in `.env`.
- `REPO_PATH` — default: the repo root (this script's parent directory's
  parent). Only needs setting explicitly if the script is copied/symlinked
  somewhere else.

## What this deliberately does NOT do (v1)

- No package signing / signature verification — trust is anchored in the
  normal `git pull` auth (HTTPS/SSH access to the repo), not a separate
  signed-package channel. The original spec (section 3.1) called for
  signature verification over a downloaded package; this MVP uses git
  directly instead, which is simpler and matches how `update.sh`/`update.bat`
  already work in this repo. Flagged back to Raffi in `docs/licensing-and-updates.md`
  as a deviation worth a sign-off if a signed-package model is wanted later.
- No automatic rollback on a failed rebuild — `docker compose up -d --build`
  failing leaves the previous containers running (Compose doesn't tear down
  the old ones until the new ones are healthy... but it doesn't guarantee
  that either). A truly robust rollback is future work; v1 just reports the
  failure clearly so an operator notices.
- No silent auto-apply surprise: the *first* time an operator enables this,
  they're opting into "pulls and rebuilds automatically on its own
  schedule," not "notify me and I'll click apply" — see the dev handoff
  doc's section 3.3 for the tradeoff. If you want a more conservative
  notify-only v1, don't wire up the cron/timer — the "Check for updates
  now" button in Settings still works standalone as a manual trigger.

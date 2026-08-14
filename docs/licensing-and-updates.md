# Licensing + Update Mechanism — implementation notes

Companion to the dev handoff doc ("TLS Fuel Platform — Dev Handoff:
Licensing + Update Mechanism"). That doc is the spec; this is what actually
got built against it, including a few deliberate simplifications worth a
quick sign-off before this goes further. Repo stays unsplit for now per
Raffi's note — Local Instance and Cloud Utility are still developed
together in one repo, one `docker-compose.yml`, gated by Compose profiles.

## 1. Scope split — confirmed, not re-done

The codebase already separates cleanly:

- **Local Instance**: `api/`, `poller/`, `frontend/`, `sync/` — polls the
  TLS-350, decodes, stores locally, serves the local dashboard. Runs fully
  standalone (`COMPOSE_PROFILES=station-core,station-ui`), no network
  dependency, no license check anywhere in this code path.
- **Cloud Utility**: `cloud/cloud-api/`, `cloud/cloud-frontend/` — multi-site
  aggregation, cross-station dashboards, supplier ordering. The only piece
  that checks a license (`cloud/cloud-api/licensing.py`).

No untangling ticket was needed — these were already independently
runnable via Compose profiles before this work started.

## 2. License gating (Cloud Utility only)

New service: **`license-server/`** — issues/validates Annual licenses
(phone-home) and generates signed Unlimited license files. SQLite-backed
(see `license-server/README.md` for why — low write volume, "keep this
simple"). Own Compose profile (`license`), own Dockerfile, never contacted
by a Local Instance.

Cloud Utility side (`cloud/cloud-api/`):
- `models.CloudLicenseState` — single-row cache of current license status.
- `licensing.py` — Annual phone-home + Unlimited offline JWT verification,
  45-day grace-clock, degrade logic. Runs once on startup, then on a loop
  (`LICENSE_CHECK_INTERVAL_HOURS`, default 24).
- `routers/license.py` — `/api/license/banner` (any user), `/api/license/status`
  + `/api/license/recheck` (admin only).
- `auth.require_not_degraded` — new dependency, applied to `stations.py`,
  `supplier.py`, and `notifications.py`'s routers.

**Degraded-mode scope, per your answer to the open question:** non-admin
users and suppliers lose access to *all* data served by those three
routers while degraded — not just ordering/reports. Admins keep full
functionality, including the new admin-only **License** page (Admin ->
License tab in the cloud frontend) showing when the license was applied,
when it expires, and whether currently in grace. `push.py`'s
`vapid-public-key` endpoint was left ungated (it's unauthenticated
subscription plumbing, not data) — flag if you want it gated too.

Historical data is never deleted on a lapse — degraded mode only blocks
*serving* it to non-admins going forward; ingestion (`ingest.py`) is never
gated at all, so new data keeps landing during a lapse, per spec.

**Key management, per your answer:** the license server holds the RSA
signing key (auto-generated + persisted to a mounted volume on first boot —
see `license-server/keys.py`). `LICENSE_SERVER_ADMIN_TOKEN_HASH` gates all
`/admin/*` routes on the license server. Unlimited license issuance
additionally requires `X-Unlimited-Passphrase`, checked against
`UNLIMITED_LICENSE_PASSPHRASE_HASH` — `PermissionGranted200` as you
specified is the dev-only fallback if that's unset.

**Update since the first pass — secrets are now hashed, not plaintext.**
Both `LICENSE_SERVER_ADMIN_TOKEN` and `UNLIMITED_LICENSE_PASSPHRASE`
originally sat in `.env`/`.env.cloud` as plaintext. They're now
`_HASH` env vars instead (SHA-256 for the admin token, bcrypt for the
human-chosen passphrase — see `license-server/auth.py`'s module docstring
for why those differ) — the actual secret is never stored anywhere,
`.env`/`docker inspect`/a backup of either file only ever exposes something
an incoming request's hash can be checked against, never the secret
itself. Run `python3 license-server/hash_secret.py --type admin-token` (or
`--type passphrase`) once to turn your chosen secret into the value that
goes in the env file.

**Update since the first pass — license activation moved into the UI.**
`CLOUD_LICENSE_TYPE`/`CLOUD_LICENSE_KEY`/`CLOUD_LICENSE_FILE` are now an
initial-deployment convenience only: they seed `CloudLicenseState` exactly
once, on a brand new deployment with an empty database
(`licensing._seed_from_env_once`). From then on, activating a license,
renewing with a new Annual key, switching to Unlimited, or clearing the
configured license entirely is done from **Admin -> License** in the cloud
frontend — paste the key or license file, no env edits or restart. Both
paths validate before persisting (phone home for Annual, verify the
signature for Unlimited) so a bad paste fails immediately with a clear
error instead of silently starting a 45-day degrade clock. Deployment-level
settings that describe *how this instance is wired up* rather than *which
license it holds* — `LICENSE_SERVER_URL`, `LICENSE_SIGNING_PUBLIC_KEY`,
`LICENSE_GRACE_DAYS`, `LICENSE_CHECK_INTERVAL_HOURS` — stay env-only; there's
no reasonable "submit this in a form" story for those.

## 3. Update mechanism (Local Instance, opt-in)

Per your answer: auto-check every N days (default 7), `git pull` +
`docker compose up -d --build`, plus a manual/remote trigger path.

- `updater/check_for_updates.py` — runs **on the host**, not in a
  container (see the file's docstring and `updater/README.md` for why: the
  container-with-a-docker-socket approach hits a real bind-mount-path
  problem that isn't worth solving for v1). Wired up via cron/systemd
  timer/Task Scheduler.
- Toggle + interval live in the local `settings` table
  (`update_check_enabled`, default **off**; `update_check_interval_days`,
  default 7), editable from the dashboard's Settings page — same
  live-without-restart pattern as everything else there. Independent of
  cloud sync and of any Cloud Utility license, per spec.
- **Remote/manual trigger**: an admin's "Check for updates" click in the
  Cloud Utility (Admin -> Stations) sets `Station.update_check_requested_at`.
  The station's own `sync` container — already polling on its normal
  interval, device-credential auth — picks that up
  (`apply_pending_update_check_request` in `sync/main.py`) and writes the
  local check-now flag. **No inbound connection to any station, ever** —
  same pull-only shape as the existing `PendingPriceUpdate` mechanism.
  This only actually fires a check if the station has update-checking
  enabled locally; the remote trigger can't turn the feature on for someone.

### Deviations from the original spec — flagging for sign-off

1. **No signed-package verification.** The spec called for a
   signed-manifest/package + a separate update-signing key. This build
   trusts `git pull` directly (the repo's normal HTTPS/SSH access control)
   instead — simpler, matches how `update.sh`/`update.bat` already work,
   and avoids standing up a second signing key for a feature the "don't
   over-build initially" guidance suggested keeping minimal. If you want
   package signing after all, that's a scoped follow-up (manifest endpoint
   + signature check before `git pull`), not a rewrite.
2. **Host-level script instead of a container.** `check_for_updates.py`
   runs via cron/systemd/Task Scheduler, not as a Compose service — see
   `updater/README.md`'s docstring for the specific docker-socket
   bind-mount problem this sidesteps.
3. **Auto-apply, not notify-then-click.** Per your answer ("auto-check…
   and do a git pull, and docker compose up -d --build"), enabling update
   checking means it pulls and rebuilds on its own schedule once due — not
   the more conservative "notify operator, they click apply" the original
   spec's section 3.3 offered as the safer v1. The manual "Check for
   updates now" button still works as a fully manual trigger if you'd
   rather not wire up the recurring cron/timer at all.

## What to configure before using any of this

- **Nothing is required for local dev.** `CLOUD_LICENSE_TYPE` unset means
  the Cloud Utility runs "unconfigured" — no gating triggers.
- To license a real Cloud Utility deployment: stand up `license-server`
  (profile `license`), generate + set `LICENSE_SERVER_ADMIN_TOKEN_HASH` via
  `hash_secret.py`, set `LICENSE_SIGNING_PUBLIC_KEY` on `cloud-api` (fetch it
  from the license server's `GET /license/public-key`), issue a license via
  the license server's admin API (see `license-server/README.md`), then
  activate it from **Admin -> License** in the cloud frontend — no need to
  put the key/file in env vars at all unless you want it pre-seeded before
  first login. See `.env.example` / `cloud/.env.cloud.example` for the full
  var list with comments.
- To enable update-checking on a station: Settings -> "Check for software
  updates" (off by default), then wire up the recurring check per
  `updater/README.md`.

## Suggested build-order status

1. ~~Split Local Instance / Cloud Utility~~ — already separable, confirmed.
2. License server (Annual + Unlimited) — done.
3. Cloud Utility gating + 45-day degrade — done.
4. Update-manifest / check endpoint — simplified per section 3's
   deviations above (no separate manifest endpoint; the updater compares
   git HEAD directly).
5. Signature verification + rollback — **not built**, per deviation #1/#3
   above. No rollback beyond "the old containers keep running if the
   rebuild fails" (Compose's default behavior, not anything explicit).
6. Automate the interval + explicit toggle — done (opt-in, off by default).

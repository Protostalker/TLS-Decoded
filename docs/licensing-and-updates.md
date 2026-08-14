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

New service: **`license-server/`** — a database of passphrases you hand
out, nothing more. SQLite-backed (see `license-server/README.md` for why —
low write volume, "keep this simple"). Own Compose profile (`license`),
own Dockerfile, never contacted by a Local Instance.

**This section was rebuilt once already, after the first pass (Annual
phone-home key + signed offline "Unlimited" license files, JWT-based) ran
into real activation friction — confusing a passphrase for a license file,
missing signing-key configuration, PEM formatting issues. Raffi's call was
to throw that out for something deliberately simpler:** one passphrase
type, always phoned home, no signing keys, no license files, no offline
verification. What's below describes the current (second, simplified)
design — see git history if you need the original spec's shape for
reference.

- You (Raffi) create a **License** by choosing the passphrase text
  yourself (`POST /admin/licenses`, e.g. `GARDENA-2026`) — not
  auto-generated, since this is a hand-issued system.
- Each license has a **use limit** (`max_uses`, default 1 — how many
  different Cloud Utility instances may activate with it) and a **fixed
  expiry set at creation** (`valid_days`, default 365; omit for
  never-expires).
- A **master passphrase** (`PermissionGranted200` by default, override via
  `MASTER_PASSPHRASE`) is auto-seeded on first boot with unlimited uses and
  no expiry.
- "1-time use" and "phones home every day" coexist via a redemption
  record: a Cloud Utility generates a random `instance_id` for itself once
  and persists it forever; its first successful check against a passphrase
  consumes one use, every check after that from the same instance is a
  free re-check. See `license-server/models.py`'s docstring for the
  mechanics.

Cloud Utility side (`cloud/cloud-api/`):
- `models.CloudLicenseState` — single-row cache of current license status
  (`configured_passphrase`, `instance_id`, plus status/dates).
- `licensing.py` — one code path: POST `{passphrase, instance_id}` to
  `{LICENSE_SERVER_URL}/license/check` on startup and on a loop
  (`LICENSE_CHECK_INTERVAL_HOURS`, default 24). A run of failures
  (unreachable OR the server says invalid) starts a 45-day grace clock
  (`LICENSE_GRACE_DAYS`); a single successful check clears it immediately.
- `routers/license.py` — `/api/license/banner` (any user), `/api/license/status`
  + `/api/license/recheck` (admin only), `/api/license/config` +
  `/api/license/activate` + `/api/license/deactivate` (admin only — submit
  or clear the passphrase from the UI).
- `auth.require_not_degraded` — dependency applied to `stations.py`,
  `supplier.py`, and `notifications.py`'s routers.

**Degraded-mode scope, per Raffi's answer to the open question:** non-admin
users and suppliers lose access to *all* data served by those three
routers while degraded — not just ordering/reports. Admins keep full
functionality, including the admin-only **License** page (Admin -> License
tab in the cloud frontend) showing when the license was applied, when it
expires, and whether currently in grace. `push.py`'s `vapid-public-key`
endpoint was left ungated (it's unauthenticated subscription plumbing, not
data) — flag if you want it gated too.

Historical data is never deleted on a lapse — degraded mode only blocks
*serving* it to non-admins going forward; ingestion (`ingest.py`) is never
gated at all, so new data keeps landing during a lapse, per spec.

**Key management.** `LICENSE_SERVER_ADMIN_TOKEN_HASH` gates all `/admin/*`
routes on the license server — it's a **hash** (SHA-256), not the token
itself, generate it with `python3 license-server/hash_secret.py`; the
plaintext token only ever exists in your own hands. Passphrases themselves
are stored as-is (not hashed) in the `licenses` table — they're reusable
codes you look up and hand out again, not one-time secrets, so there's
nothing to gain from hashing them.

**License activation lives in the UI.** `CLOUD_LICENSE_KEY` is an
initial-deployment convenience only: it seeds `CloudLicenseState` exactly
once, on a brand new deployment with an empty database
(`licensing._seed_from_env_once`). From then on, activating a license,
switching to a new passphrase, or clearing the configured license entirely
is done from **Admin -> License** in the cloud frontend — paste the
passphrase, no env edits or restart. Activation validates (phones home)
before persisting, so a bad paste fails immediately with a clear error
instead of silently starting a 45-day degrade clock. Deployment-level
settings that describe *how this instance is wired up* rather than *which
license it holds* — `LICENSE_SERVER_URL`, `LICENSE_GRACE_DAYS`,
`LICENSE_CHECK_INTERVAL_HOURS` — stay env-only; there's no reasonable
"submit this in a form" story for those.

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

- **Nothing is required for local dev.** `CLOUD_LICENSE_KEY` unset means
  the Cloud Utility runs "unconfigured" — no gating triggers. (The license
  server's own auto-seeded master passphrase, `PermissionGranted200`, works
  out of the box if you do want to test the gated path.)
- To license a real Cloud Utility deployment: stand up `license-server`
  (profile `license`), generate + set `LICENSE_SERVER_ADMIN_TOKEN_HASH` via
  `hash_secret.py`, issue a passphrase via the license server's admin API
  (see `license-server/README.md`), then activate it from **Admin ->
  License** in the cloud frontend — no need to put it in an env var at all
  unless you want it pre-seeded before first login. See `.env.example` /
  `cloud/.env.cloud.example` for the full var list with comments.
- To enable update-checking on a station: Settings -> "Check for software
  updates" (off by default), then wire up the recurring check per
  `updater/README.md`.

## Suggested build-order status

1. ~~Split Local Instance / Cloud Utility~~ — already separable, confirmed.
2. License server (simple passphrase + redemption model) — done.
3. Cloud Utility gating + 45-day degrade — done.
4. Update-manifest / check endpoint — simplified per section 3's
   deviations above (no separate manifest endpoint; the updater compares
   git HEAD directly).
5. Signature verification + rollback — **not built**, per deviation #1/#3
   above. No rollback beyond "the old containers keep running if the
   rebuild fails" (Compose's default behavior, not anything explicit).
6. Automate the interval + explicit toggle — done (opt-in, off by default).

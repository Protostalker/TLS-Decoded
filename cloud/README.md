# TLS-Decoded Cloud

Multi-station cloud layer on top of the per-station stack in the repo root.
Lets a customer with one or more stations log into a central portal and see
their station(s) from anywhere, without port-forwarding or a stable IP at
each site. Design background and all the "why" behind these decisions is in
[`CLOUD-ARCHITECTURE.md`](../CLOUD-ARCHITECTURE.md) at the repo root — this
file is the practical "how to run it" companion.

**Nothing about the per-station stack changes.** Every station still runs
`db` + `poller` + `api` + `frontend` exactly as before, fully standalone —
cloud sync is additive and optional (see `sync/` at the repo root).

## The three tiers

- **T1 — Station dashboard.** Cloud-served version of the local dashboard,
  scoped to whichever station is selected, reading the cloud DB's mirrored
  copy of that station's data.
- **T2 — Login portal** (`/`). Customer login → list of assigned station(s)
  → combined stats across all of them if more than one.
- **T3 — Admin portal** (`/admin`). Internal only. Provision customers,
  stations (issuing the device credential), users, assignments, and manage
  sessions.

All three are served by one app — `cloud-frontend` (React) talking to one
`cloud-api` (FastAPI) — per the data-flow diagram in
`CLOUD-ARCHITECTURE.md`.

## Layout

```
cloud/
├── docker-compose.cloud.yml   # standalone copy of the cloud services — see "Dedicated cloud box" below
├── .env.cloud.example         # env file for that standalone copy
├── cloud-api/                 # Ingest API + T1/T2/T3 app API (FastAPI)
│   ├── models.py               # tenancy tables + mirrored cloud_* tables
│   ├── auth.py                 # device credential + DB-backed sessions
│   └── routers/
│       ├── ingest.py            # station -> cloud pushes land here
│       ├── auth_router.py       # T2 login/logout/me/sessions
│       ├── stations.py          # T1 (per-station) + T2 (picker/combined stats)
│       └── admin.py             # T3
└── cloud-frontend/             # React + Vite + react-router → nginx
    └── src/pages/
        ├── LoginPage.jsx, StationsPage.jsx, StationDashboardPage.jsx, AdminPage.jsx
```

The station-side half of this feature — the `sync` container that pushes
data out — lives at the repo root (`sync/`), alongside `api/`/`poller/`.

**The root `docker-compose.yml` is the one file that matters day to day.**
It already contains everything — station services (`db`/`api`/`poller`/
`frontend`/`sync`) and cloud hub services (`cloud-db`/`cloud-api`/
`cloud-frontend`) — as one file, one `.env`, one `docker compose up`.
Which services actually start is controlled by `COMPOSE_PROFILES` in
`.env`, not by editing the YAML — see **Deployment modes** in the root
`README.md`. `cloud/docker-compose.cloud.yml` is a second, standalone copy
of just the cloud section, kept for the day the cloud hub moves to its own
dedicated box — see "Dedicated cloud box" below. Until then, ignore it and
use the root file.

## Running it

Easiest path: `./install.sh` from the repo root — it asks what kind of box
this is (local station / cloud server / poll-sync / complete-demo) and
handles `.env`, profiles, and secrets for you. See the root `README.md`'s
**Quick start** and **Deployment modes**.

Doing it by hand instead — **one box doing everything** (station + cloud
together, e.g. a prototype or demo):

```bash
cp .env.example .env
# COMPOSE_PROFILES=station-core,station-ui,cloud
# fill in .env — station vars (DB_PASSWORD, SECRET_KEY, ...) and the
# "Cloud hub" section (CLOUD_DB_PASSWORD, CLOUD_ADMIN_EMAIL/PASSWORD, ...)

docker compose up -d --build
```

- Cloud portal: **http://localhost:5100**
- Cloud API docs: **http://localhost:8100/docs**
- Station's own local dashboard keeps working exactly as before at
  **http://localhost:5005**

If this box is station-only (no cloud) set `COMPOSE_PROFILES=station-core,station-ui`;
cloud-only (no station hardware) set `COMPOSE_PROFILES=cloud`; a poll-sync
station with no local dashboard set `COMPOSE_PROFILES=station-core`. Same
`docker compose up -d --build` either way — the profile is what changes.

### Dedicated cloud box (later)

When HTS hosts the real cloud hub on its own separate machine, `cloud/` is
the deliverable that moves — copy the folder over, fill in a real
`.env.cloud`, and run its own standalone compose file there instead of the
root one:

```bash
cd cloud
cp .env.cloud.example .env.cloud   # fill in real values
docker compose -f docker-compose.cloud.yml --env-file .env.cloud up -d --build
```

No code changes either way. Each customer's station keeps running the root
`docker-compose.yml` (`COMPOSE_PROFILES=station-core` or
`station-core,station-ui`, no `cloud` profile) locally, pointed at the new
hub's real domain via `CLOUD_INGEST_URL` instead of the temporary DDNS one
(see "Provisioning a station" below).

## Provisioning a station

1. Log into the cloud portal as an admin (`http://localhost:5100`, the
   bootstrap account from `CLOUD_ADMIN_EMAIL`/`CLOUD_ADMIN_PASSWORD`).
2. **Admin → Customers** — create the customer if they don't exist yet.
3. **Admin → Stations** — provision a station under that customer. The
   device credential (`device_id` + `device_secret`) is shown **exactly
   once** — copy it now.
4. Enable sync on the station itself. Two ways, same end state — the
   `sync` service reads its config from the local `settings` table, and
   both paths land there (see "How sync gets configured" below):

   **A. From the station's own local dashboard (no restart, works on an
   already-running station):** open the gear icon → **Cloud sync** →
   paste in the cloud URL, device ID, and device secret from step 3, set
   an interval, check **Cloud sync** enabled, **Save**. Sync starts
   pushing within ~15 seconds.

   **B. Via `.env`, before first bringing the station up:**
   ```
   CLOUD_INGEST_URL=http://<cloud-host>:8100      # or the real domain later
   STATION_DEVICE_ID=<from step 3>
   STATION_DEVICE_SECRET=<from step 3>
   ```
   then `docker compose up -d` — these seed the same settings the
   dashboard edits, and sync auto-enables since all three are present.
   Either way it's a no-op/idle state before this — no restart of `api`
   or `poller` needed, and the local dashboard shows "Not synced yet" /
   "Never synced" until it's configured one of these two ways.
5. **Admin → Users** — create a login for the customer's staff and assign
   them to the station(s) they should see.

### How sync gets configured

`CLOUD_INGEST_URL` / `STATION_DEVICE_ID` / `STATION_DEVICE_SECRET` (env
vars, path B above) only **seed** the `cloud_sync_url` / `cloud_sync_device_id`
/ `cloud_sync_device_secret` rows in the station's local `settings` table
the first time the `sync` container ever starts — after that, the local
dashboard's Settings panel (path A) is the live source of truth, same
pattern already used for `poll_interval_minutes`. The `sync` service
re-reads `cloud_sync_enabled` / `cloud_sync_url` / the credential /
`cloud_sync_interval_minutes` from that table every ~15s, so toggling sync
on/off, repointing it at a different cloud host, or rotating a credential
all take effect without restarting any container. The dashboard also shows
a live "last synced" status, sourced from `cloud_sync_last_synced_at`,
which `sync` writes after every successful cycle.

Sync cadence defaults to 30 minutes and is adjustable per station from
**Admin → Stations**, or directly on the station's own dashboard (Settings
→ Cloud sync → sync interval) — same live-editable pattern the poller uses
for its own poll interval. Note: v1 sync is one-way (station → cloud), so
the T3-side interval field is a record of what the station *should* be set
to, not something pushed down automatically yet — see "Open questions" #3
in `CLOUD-ARCHITECTURE.md`.

## Auth model

Two independent credential types, matching `CLOUD-ARCHITECTURE.md`:

- **Station device credential** — `device_id` + `device_secret`, checked
  against `stations` in the cloud DB, used only by `sync` → the Ingest API.
- **User login** — email + password, producing a DB-backed session (not a
  JWT — required for "never expires" + admin-revocable to both work; see
  `sessions` table). Session duration is chosen at login: short-lived,
  90 days, or never — and any session can be revoked immediately from
  **Admin → Users → Manage** regardless of what was chosen.

## What's mirrored, and how sync stays idempotent

The cloud DB holds `cloud_tanks` / `cloud_readings` / `cloud_delivery_events`
/ `cloud_fuel_prices` / `cloud_poll_log` — same shape as the station's local
tables, each tagged with `station_id`, plus a `local_id` carrying the row's
id (or, for tanks, the station-local tank id) from the station's own
database. `(station_id, local_id)` is the upsert key the Ingest API applies
every push against — retrying a batch after a dropped connection is always
safe, never creates duplicates.

The `sync` service tracks its own progress locally per table (`readings`
and `poll_log` by row id since they're append-only at the source; `tanks` /
`delivery_events` / `fuel_prices` by `updated_at` since those get edited
after their first push — a delivery merge, a manual price edit, a capacity
correction). Nothing is ever deleted from the station's local DB to make
this work, and if the cloud is unreachable the checkpoint simply doesn't
advance — the next tick (or the one after) picks up exactly where it left
off.

## Staleness — two separate signals

Cloud-served T1 shows **"cloud data as of {last sync time}"** — how fresh
the mirrored copy is — which is deliberately distinct from the station's
own **"last poll"** indicator, which is about the gauge itself. If a
station's internet or power drops, the cloud keeps serving the last
successfully synced numbers instead of nothing; the staleness badge is what
makes it obvious you're looking at "last known good," not live data.

## Weather (optional, per station)

Set a zip code on a station (**Admin → Stations → Zip**) to get a weather
panel on that station's T1 dashboard, plus a condensed chip and any active
forecast-driven heads-up (rain, freeze, heat, high wind, snow — e.g. "check
tank vent cap covers" ahead of rain) rolled up on the T2 hub. Uses two free,
keyless upstreams (Zippopotam.us for geocoding, api.weather.gov for the
forecast — both US-only), cached in-process for 30 minutes per zip. No zip
set, or an upstream hiccup, just means the panel doesn't render — nothing
else depends on it.

Also set a station's **Timezone** (Admin → Stations, IANA name like
`America/Los_Angeles`; defaults to Pacific if left blank) — this is what
"today" means for that station's stats on T1/T2. Get this right or
"today's" numbers won't match the station's own local dashboard.

## Pricing (cloud → station)

Each station's T1 dashboard has a **Pricing — all products** panel showing
every tank's current cost/tax/sale price and live margin, mirrored from the
station. Submitting an update there doesn't write to the station directly —
v1 sync is one-way (station → cloud) — it queues a `PendingPriceUpdate`
row instead. The station's own `sync` container polls for pending updates
every ~15s tick (independent of its push interval), applies them to the
local `fuel_prices` table exactly as if someone had typed them in at the
station, and acks. The resulting row flows back up through the normal
one-way push on the next cycle. The panel shows "queued" vs. "applied at
{time}" so it's honest about the latency — usually seconds if the station
is online, longer if it's offline until it reconnects.

## Local dev (without Docker)

```bash
cd cloud/cloud-api
pip install -r requirements.txt
CLOUD_DATABASE_URL=postgresql://tls_cloud:tls_cloud_local@localhost:5433/tls_decoded_cloud \
  uvicorn main:app --reload

cd cloud/cloud-frontend
npm install
npm run dev   # proxies /api to http://cloud-api:8000 in Docker; set vite.config.js's target to localhost:8000 for bare-metal dev
```

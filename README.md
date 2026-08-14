# TLS-Decoded

Self-hosted fuel tank monitoring for a **Veeder-Root TLS-350** automatic tank
gauge (ATG). Polls the gauge over the network, stores every reading in
Postgres, and serves a live dashboard: tank levels, consumption/refuel
history, reorder forecasts, and CSV exports.

Built for a 3-tank gas station (Unleaded / Super / Diesel), but tank count,
sizes, and thresholds are all configurable.

---

## Features

- **Live tank gauges** — desktop shows a scrollable, centered row of cylinder
  gauges; mobile shows a tappable 2×2 grid of square tiles.
- **Reorder forecast** — days until reorder threshold / days until empty,
  with a confidence rating based on how much history is available.
- **Configurable, clock-aligned polling** — set the poll interval and toggle
  clock alignment (e.g. every 30 min lands on :00/:30, not on whatever
  minute the poller happened to start) live from the dashboard. No restart
  needed. A "Poll now" button forces an out-of-cycle read.
- **Recent readings table** — last 15 polls for the selected tank, 5 visible
  with scroll for the rest.
- **Per-poll consumption log** — gallons and gal/hr between each pair of
  consecutive polls, next to the delivery history.
- **Delivery (refuel) detection** — auto-detects volume jumps, re-polls a
  few times to let the number settle (a delivery can take 10-20+ minutes),
  and estimates a "gross" figure that accounts for fuel sold at the same
  time the truck was unloading. Increases spread across multiple polls are
  merged into a single session total instead of showing up as separate
  entries.
- **Confirm / edit / manually log deliveries** — correct an auto-detected
  total against the driver's paper ticket, or log a delivery that
  auto-detection missed entirely. The dashboard's Delivery panel is where
  all of this lives.
- **Fun stats** — today's/week's consumption, 30-day average, estimated
  tank turnover, days since last delivery, 7-day temperature range, and a
  water-level flag.
- **Tank size correction** — edit a tank's capacity or reorder threshold
  from Settings if the installed size differs from the initial estimate;
  the poller won't overwrite your correction.
- **CSV exports** — per-tank raw readings, all-tanks combined, or a
  day-by-day **Monthly Ledger** shaped like a manual spreadsheet (GAL /
  ADDED / SOLD per tank, plus a total).
- **Device ID** — a 32-char hex ID (view/generate/edit), the original
  placeholder for a future cloud-sync phase. Superseded by the real device
  credential the cloud hub now issues (see **Cloud (multi-station)** below)
  when cloud sync is enabled — this field is kept for backward compatibility
  and still just a local display value otherwise.
- **Cloud sync (optional)** — a station can push its data outbound on a
  timer to a central cloud hub for remote/multi-station viewing, without any
  inbound connection or stable IP at the station. Fully optional and
  additive — see **Cloud (multi-station)** below. The station works exactly
  as described above with this disabled, which is the default.
- **Pricing, one screen for every product** — cost, tax/fees, and sale price
  per tank, live margin and today's profit, full price history. Update
  every product from one panel instead of switching tanks one at a time —
  works the same way locally and from the cloud portal (a cloud-side update
  queues to the station and applies within seconds of it next checking in).
- **Automated sale price (optional, Commander)** — a station running
  [commander-reader](#automated-pricing-commander-price-sync) in front of a
  Verifone Commander can have the live pump (sale) price synced in
  automatically on an hourly timer instead of typed in. Cost per gallon
  stays a manual entry either way — see **Automated pricing (Commander
  price sync)** below for why, and for the grade-assignment picker and
  station-wide tax rate setting that go with it.
- **Weather + maintenance heads-up (optional, cloud)** — set a station's zip
  code from the cloud admin panel to get current conditions plus
  forecast-driven reminders (rain → check tank vent cap covers, freeze →
  heat tape, high wind → secure covers, etc.) on that station's dashboard
  and rolled up on the multi-station hub.
- **Branding** — set a station's dashboard colors from Settings: pick a
  named fuel-brand preset (Arco, Sinclair, Chevron, Mobil, Pemex, Buc-ee's —
  color associations only, no trademarked logo artwork bundled) or set 3
  custom colors, plus an optional custom logo upload. The accent color
  drives the page background; everything else (surfaces, borders, text) is
  derived from it by contrast so it stays readable regardless of how light
  or dark the accent is. Tank fill colors and the gauge illustration stay
  neutral (status, not brand). If a station syncs to the cloud, its
  branding mirrors up automatically and applies to that station's page on
  the cloud portal (T1), plus its own themed card in the multi-station
  picker (T2) — see **Cloud (multi-station)** below for how the two are
  scoped differently.

---

## Stack

| Service    | Tech                              | Port |
|------------|------------------------------------|------|
| `db`       | postgres:16-alpine                 | 5432 |
| `api`      | FastAPI + SQLAlchemy               | 8000 |
| `poller`   | Python, polls on a live schedule   | —    |
| `frontend` | React + Vite + Recharts → nginx    | 5005 |
| `sync`     | Python, pushes to the cloud hub on a timer (idle until configured) | — |
| `cloud-db`, `cloud-api`, `cloud-frontend` | Optional cloud hub for multi-station remote viewing | 5433, 8100, 5100 |

**All of the above live in one `docker-compose.yml`.** Which services
actually start is controlled by `COMPOSE_PROFILES` in `.env` — `install.sh`
sets this for you based on the deployment mode you pick; see **Deployment
modes** below.

## Hardware

- TLS-350 reached over TCP via a StarTech (or similar) serial-to-Ethernet
  adapter in TCP Server mode.
- Command format: `\x01` + 3-digit code (e.g. `\x01200` = all tanks).
- Response: ASCII display table ending with ETX (`\x03`).
- Working commands: `200` (all tanks), `201`/`202`/`203` (per tank).
- Set a DHCP reservation for the adapter's MAC address so its IP doesn't
  change under you.

---

## Quick start

```bash
git clone https://github.com/Protostalker/TLS-Decoded.git
cd TLS-Decoded
./install.sh
```

`install.sh` is interactive and re-runnable: it asks what kind of
deployment this box is, generates secrets, writes `.env` and
`config/tls-decoded.yaml`, sets the docker compose profile(s) that control
which services start, and optionally brings the stack up for you. Re-run it
any time — every answer defaults to what's already configured, and none of
it touches your database or historical readings.

Prefer to do it by hand? `cp .env.example .env` and
`cp config/tls-decoded.yaml.example config/tls-decoded.yaml`, fill them in
yourself (see **Deployment modes** below for what `COMPOSE_PROFILES` needs
to be), then `docker compose up -d --build`.

Dashboard: **http://localhost:5005**
API docs (Swagger UI): **http://localhost:8000/docs**

`.env` and `config/tls-decoded.yaml` are both gitignored — they hold your
real station details and never get committed or touched by a `git pull`.

---

## Deployment modes

One `docker-compose.yml` covers every deployment shape; `COMPOSE_PROFILES`
in `.env` decides which services actually start (services aren't part of
any profile are never started — an empty/unset `COMPOSE_PROFILES` starts
nothing). `install.sh` sets this for you based on the mode you pick:

| Mode | `COMPOSE_PROFILES` | What runs |
|---|---|---|
| Local station | `station-core,station-ui` | Full station stack + its own local dashboard |
| Cloud server | `cloud` | Cloud hub only — no station hardware on this box |
| Poll-sync station | `station-core` | Station data pipeline + push to a remote cloud, but **no local dashboard** on this box |
| Complete / demo | `station-core,station-ui,cloud` | Everything, one box — good for demos or a prototype |

Poll-sync is for a site where nobody should look at a local URL at all —
staff only ever check the cloud portal, so the `frontend` container never
even starts here, while `db`/`api`/`poller`/`sync` run exactly as normal
underneath it.

---

## Updating (pulling future changes)

```bash
./update.sh      # or update.bat on Windows
```

Just `git pull` + `docker compose up -d --build` for whatever's enabled via
`COMPOSE_PROFILES` — a couple of things make this safe to run any time:

- `.env` and `config/tls-decoded.yaml` are gitignored, so a pull never
  overwrites your local station config or credentials.
- Poll interval, alignment, device ID, and tank capacity/reorder thresholds
  now live in the database (editable from Settings), not the YAML file —
  they survive rebuilds automatically.
- The Postgres data lives in a named Docker volume (`pgdata`), so
  `docker compose up -d --build` rebuilds the app containers without
  touching your historical readings. Schema changes (new columns/tables)
  are applied automatically on startup via idempotent migrations in both
  the API and poller.

If you want to see what changed before updating: `git log --oneline -10`
or check the repo's commit history on GitHub. Run `./install.sh` again
instead of `update.sh` if you also want to change deployment mode, rotate
secrets, or reconfigure ports.

**Prefer this to happen on its own?** `updater/check_for_updates.py` does
the same `git pull` + `docker compose up -d --build`, but only when a check
is actually due — wire it up as an hourly cron/systemd-timer/Task Scheduler
entry (see `updater/README.md`) and it runs unattended. Off by default —
turn it on from the dashboard's Settings -> Check for software updates, or
it stays a no-op. Independent of Cloud sync and of any Cloud Utility
license: works the same whether or not this station is connected to a
cloud hub. See `docs/licensing-and-updates.md` for the full picture.

---

## Using the dashboard

**Tank gauges** (top) — click/tap a tank to select it; everything below the
gauges (chart, stats, tables, deliveries) reflects the selected tank.

**Settings (gear icon, top right)**
- *Tank sizes* — correct capacity/reorder threshold per tank.
- *Poll interval* — pick a preset or enter custom minutes; toggle clock
  alignment; "Poll now" for an immediate read.
- *Device ID* — view, copy, regenerate, or manually set the hex ID used for
  a future cloud-sync feature.
- *Commander price sync* — optional auto-sync of sale price from a
  `commander-reader` instance, plus per-tank grade assignment. Off by
  default; see **Automated pricing (Commander price sync)** below.
- *Tax rate* — one station-wide rate applied automatically to every new
  price entry, manual or Commander-synced.

**Delivery panel**
- Auto-detected deliveries show a net figure and, when different, an
  "est. gross" figure that accounts for concurrent sales.
- "Combined from N polls" means the poller merged a delivery that showed up
  across multiple poll intervals into one session.
- **Confirm / edit** any entry to lock in the true number (e.g. from a
  delivery ticket) — once confirmed it won't be touched by auto-merging.
- **+ Log delivery** manually reports a delivery that auto-detection missed.

**Pricing — all products** — cost, tax/fees, sale price, live margin, and
today's profit for every tank at once, plus per-tank history/editing lower
down. Update every product's price without switching which tank is
selected. The cloud portal has the same panel per station — a price
entered there queues to the station and applies within seconds of it next
checking in (v1 sync is otherwise one-way, station → cloud only; this is
the one narrow exception).

**Export bar** (bottom) — pick a month and download raw per-tank CSV,
all-tanks CSV, or the Monthly Ledger CSV (Day / GAL / ADDED / SOLD per tank
+ total, matching a typical manual spreadsheet).

**Branding** (Settings ⚙) — pick a preset (a handful of well-known fuel
brands, by color association only) or set 3 custom colors, and optionally
upload a logo (stored as-is, no external file hosting needed). Applies
immediately, no restart. If cloud sync is on, the same colors/logo mirror up
on the next sync cycle.

---

## Automated pricing (Commander price sync)

Optional, station-side, off by default. Connects tls-decoded to a separate
project — **commander-reader** (its own repo, its own deployment, not part
of this `docker-compose.yml` — runs independently on the station's Docker
host) — a small read-only REST proxy that sits on the station's LAN in front
of a **Verifone Commander** pump controller/POS, polling it over NAXML and
caching the result at `http://<host>:8200`. tls-decoded's `poller` talks to
*commander-reader*, never to the Commander unit directly.

**Why only the sale price is automatic, never the cost.** Commander
controls what's live at the pump — the retail sale price — and has no way
to know what the station paid its fuel supplier; that number only ever
comes from a supplier invoice. So this integration syncs
`sale_price_per_gallon` on an hourly timer and leaves `cost_per_gallon` a
manual entry via the Pricing panel, same as always. **That's the one
remaining manual step** — see *Next step* below for the plan to close it.

**Setup — Settings ⚙ → Commander price sync:**
1. Enable the checkbox and enter the `commander-reader` URL
   (`http://<host>:8200`), price tier (cash/credit), and sync interval
   (default 60 min). Save.
2. Click **Test connection now** — this also fetches the live grade list.
   The panel shows the equivalent `curl http://<host>:8200/health` command
   too, for checking from the Docker host directly if the button says
   unreachable but you suspect a Docker-networking quirk rather than
   `commander-reader` actually being down.
3. **Assign grades to tanks** — grade IDs are per-station Commander config,
   never portable across stations and not reliably guessable (duplicate
   grade names with different IDs are common). The panel lists every grade
   the Commander reports (ID, name, live price) with a dropdown per tank;
   anything left unassigned shows explicitly as N/A so nothing syncs by
   accident. Confirm the correct mapping with whoever set up the station's
   Commander before assigning — don't guess from the name alone.
4. A tank needs at least one manual price entry (a starting cost) before
   sync can begin — there's nothing to carry the cost forward from
   otherwise. After that, sync carries the last known cost forward
   unchanged and only updates the sale price each cycle.

**Tax rate** (Settings ⚙ → Tax rate) — set once, station-wide, applied
automatically to every new price entry (manual or Commander-synced) instead
of being typed in each time.

**Status** — a lightweight heartbeat checks `commander-reader`'s `/health`
every 5 minutes (independent of the hourly full sync) so "last checked" in
Settings stays current within minutes rather than up to an hour stale.

**Next step:** the plan is to check whether the station's fuel distributor
will allow polling their pricing data directly (API/EDI feed, if they
expose one) — that would be the natural way to also automate cost per
gallon, the same way Commander automates sale price. Until/unless that
access is granted, cost stays a quick manual update via the Pricing panel
whenever a new supplier invoice comes in — the rest of this integration
works fully today regardless of that outcome.

---

## API reference

All endpoints are under `/api`. Full interactive docs at `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /dashboard` | Everything the main view needs in one call |
| `GET /tanks`, `GET /tanks/{id}` | Tank config + latest reading |
| `PUT /tanks/{id}` | Correct capacity / reorder threshold / name |
| `GET /tanks/{id}/readings` | Raw readings (supports `from`, `to`, `limit`) |
| `GET /tanks/{id}/consumption` | Per-poll consumption deltas |
| `GET /tanks/{id}/stats` | Today/week/30d stats, water alert, turnover |
| `GET /tanks/{id}/prediction` | Reorder forecast for one tank |
| `GET /tanks/{id}/deliveries` | Delivery history |
| `PUT /deliveries/{id}` | Confirm/correct a delivery total |
| `POST /tanks/{id}/deliveries` | Manually log a delivery |
| `GET /tanks/{id}/export`, `GET /export` | CSV export (raw), per-tank / all-tanks |
| `GET /export/monthly-summary` | Monthly Ledger CSV |
| `GET /settings`, `PUT /settings` | Poll interval/alignment, device ID, remote sync, Commander price sync config, tax rate |
| `POST /settings/poll-now` | Request an immediate poll |
| `POST /settings/device-id/regenerate` | New random device ID |
| `POST /settings/commander/test` | On-demand `commander-reader` health check + live grade list |
| `GET /health` | Liveness check |

---

## Cloud (multi-station)

Optional layer on top of everything above: a customer with one or more
stations can log into a central cloud portal and see their station(s) from
anywhere, with no port-forwarding or stable IP required at any station.
Each station pushes its data outbound to the cloud hub on a timer (default
every 30 min); the hub holds a mirrored copy and serves the dashboard from
that. If a station drops offline, the cloud keeps showing its last known
good numbers instead of nothing.

This is entirely additive — every station keeps running standalone exactly
as described above regardless of the cloud hub. `docker-compose.yml`
contains all of it as one file, gated by `COMPOSE_PROFILES` (see
**Deployment modes** above), and even with the cloud hub running, a given
station's `sync` service stays idle until you configure it (from the local
dashboard's Settings panel, or via env vars) — nothing gets pushed anywhere
by default.

The cloud portal also gets its own **Pricing** panel per station (queues an
update back to the station — see **Using the dashboard** above) and an
optional **weather** panel/heads-up per station once you set a zip code
from Admin → Stations.

**Branding** mirrors up the same way: whatever colors/logo a station has set
locally show up on that station's own page in the cloud portal (T1), fully
themed — the cloud never sets or overrides it, it only reflects what the
station last pushed. The multi-station picker (T2) never re-themes its own
chrome to match any one station (useful if a customer runs stations under
different brands) — but each station's card in the grid shows that
station's full theme (colors, logo), so you can tell stations apart at a
glance without opening any one of them.

Full setup, the auth model, and provisioning steps are in
[`cloud/README.md`](cloud/README.md). Design rationale for how this is put
together is in [`CLOUD-ARCHITECTURE.md`](CLOUD-ARCHITECTURE.md).

**Licensing** (Cloud Utility only — a station running standalone never
touches this): a simple passphrase, hand-issued and use-limited, always
phoned home to `license-server` (45-day grace on a lapse) — no signing
keys, no license files. See
[`license-server/README.md`](license-server/README.md) for issuing licenses
and [`docs/licensing-and-updates.md`](docs/licensing-and-updates.md) for the
full picture, including what's still open for sign-off.

---

## Project structure

```
tls-decoded/
├── install.sh                     # interactive, re-runnable installer — start here
├── update.sh, update.bat          # git pull + docker compose up -d --build
├── docker-compose.yml             # every service, gated by COMPOSE_PROFILES
├── NOTICE.md                      # ownership / support info
├── config/
│   ├── tls-decoded.yaml.example   # template — copy to tls-decoded.yaml
│   └── tls-decoded.yaml           # your real config (gitignored)
├── poller/
│   ├── main.py                    # scheduling loop, delivery merge logic, DB persistence
│   ├── network_driver.py          # TCP socket + display-format parser
│   ├── mock_driver.py             # fake data for local dev (network.mock: true)
│   ├── analytics.py               # consumption rate, delivery detection
│   ├── commander_prices.py        # optional: syncs sale price from commander-reader
│   └── config.py / models.py
├── api/
│   ├── main.py
│   ├── models.py, schemas.py
│   └── routers/
│       ├── tanks.py, readings.py, insights.py
│       ├── deliveries.py          # confirm / manually log
│       ├── pricing.py             # cost/tax/sale price history + margin calc
│       ├── settings.py            # poll interval, device ID, cloud sync + Commander sync config, tax rate
│       └── export.py              # CSV exports
├── frontend/
│   └── src/components/
│       ├── Dashboard.jsx
│       ├── TankGauge.jsx          # desktop cylinder / mobile square
│       ├── FuelChart.jsx, StatsPanel.jsx
│       ├── ReadingsTable.jsx, ConsumptionPanel.jsx, DeliveryPanel.jsx
│       ├── PricingPanel.jsx, AllPricingPanel.jsx   # per-tank + all-products pricing
│       ├── ExportPanel.jsx, SettingsPanel.jsx, Footer.jsx
├── sync/                          # optional 5th station container — pushes to the cloud hub
│   ├── main.py                    # checkpointed batch pushes, retry w/ backoff, applies queued price updates
│   └── config.py
└── cloud/                         # optional cloud hub — see cloud/README.md
    ├── docker-compose.cloud.yml
    ├── cloud-api/                 # Ingest API + T1/T2/T3 app API
    │   └── weather.py             # zip -> forecast + maintenance recommendations
    └── cloud-frontend/            # login (T2), station dashboard (T1), admin (T3)
```

---

## Troubleshooting

**Dashboard is blank** — check the frontend was built with the `production`
Docker target (nginx), not `development` (Vite dev server on a different
port). `docker-compose.yml`'s `frontend.build.target` should be
`production`.

**Check logs:**
```bash
docker logs tls-decoded-frontend-1
docker logs tls-decoded-api-1
docker logs tls-decoded-poller-1
docker logs tls-decoded-sync-1     # if cloud sync is enabled — see cloud/README.md
```

**Poller can't reach the gauge** — confirm the adapter's IP in
`config/tls-decoded.yaml` (`network.host`), and that a DHCP reservation is
set so the IP doesn't drift. Set `network.mock: true` to develop against
fake data while troubleshooting hardware.

**Commander price sync shows "unreachable"** — check Settings ⚙ → Commander
price sync for the last error, and use the **Test connection now** button
there (or the `curl` command it prints) to check `commander-reader`
directly. Common causes: `commander-reader` isn't running, the URL/port is
wrong, or the poller container can reach the Docker host network
differently than your own machine does (the `curl` command is specifically
for ruling that last one in/out). This never affects tank polling or the
rest of the dashboard — it's fully independent, and pricing just stays
manual while it's down.

**Schema errors after pulling an update** — both the API and poller run
idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations on
startup, so a plain rebuild/restart should self-heal. If something still
looks off, restart the `poller` service last: it runs a couple of
migrations the API also runs, so either one catches up the schema
regardless of start order.

---

## Roadmap / not yet built

- Reorder-threshold alerts (browser/desktop notifications)
- Side-by-side tank comparison view
- Broader remote config from the cloud side (poll interval, tank capacity,
  etc. pushed down to a station) — pricing is the one thing that can be
  pushed down today (see **Pricing** above); v1 cloud sync is otherwise
  one-way, station → cloud only. See `cloud/README.md` and
  `CLOUD-ARCHITECTURE.md`'s open questions.
- **Automated cost per gallon** — currently the one manual step left in
  pricing (see **Automated pricing (Commander price sync)** above). Next
  step is finding out whether the station's fuel distributor will allow
  polling their pricing data directly; if so, cost could sync the same way
  sale price does today. Until/unless that access exists, cost stays a
  manual entry.

---

## Support / ownership

Built by **Healthcare Tech Solutions** — see [`NOTICE.md`](NOTICE.md) for
contact info and licensing/resale terms. The same info is shown in the
footer of every page in both the local dashboard and the cloud portal.

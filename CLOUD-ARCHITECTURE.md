# TLS-Decoded Cloud Architecture — Design Plan

Status: **built.** Decisions below are confirmed by the project owner (Raffi) and implemented per the build order — see [`cloud/README.md`](cloud/README.md) for how to run it and the provisioning flow. This doc remains the design rationale/handoff reference; the open questions section at the bottom still reflects real unresolved decisions (e.g. one-way vs. two-way sync).

## Context, for a fresh session

`tls-decoded` is a self-hosted Veeder-Root TLS-350 fuel tank monitoring system. The existing, working piece is a per-station stack: `db` (Postgres) + `poller` (reads the tank gauge over serial/Ethernet) + `api` (FastAPI) + `frontend` (React, referred to below as **T1**), all in one `docker-compose.yml`, running today at one station. That stack is not changing.

This document describes a new layer on top: letting a customer with one or more stations log into a central cloud portal and see their station(s) from anywhere, without relying on port-forwarding or a stable IP at each site. Below, "station" means one physical site's existing four-container stack.

## The tier model

- **T1 — Station dashboard.** The existing frontend, unchanged in its component code. Under the cloud model it gets re-pointed at cloud-held data instead of a local API (see Data flow).
- **T2 — Login portal.** Customer-facing login. After auth, a user sees the station(s) assigned to them. One station or many, they always land here first. If they have more than one, T2 also has a **combined stats page** across all their assigned stations — same pattern as the tank-combining `/api/stats/summary` endpoint already built, one level up.
- **T3 — Admin portal.** Internal only, served at a distinct path (e.g. `website.ddns.net/admin`). Admins create customer accounts, provision stations, assign users to stations, and manage sessions (see Auth).

## Confirmed: stations push out, cloud serves T1 itself (Option B)

Settled — no hyperlink handoff from T2 to a station's own box. Stations sync their data **outbound** to a cloud hub; the cloud hub holds a mirrored, per-station copy of the data; T1 is served entirely from the cloud, reading that mirrored copy for whichever station is selected. No station ever needs to accept an inbound connection from anyone.

This also gets you something for free that motivated the choice: if a station's internet or power goes down, the cloud still has the last successfully synced numbers, so a viewer sees "last known good" data instead of nothing. T1-from-cloud should show a clear "data as of {last sync time}" indicator so it's obvious when what you're looking at is stale versus live — this is a second, separate staleness signal from the station's own internal "last poll" indicator, and both matter for different reasons (local poll lag vs. cloud sync lag).

## Data flow

```
┌─────────────── existing per-station stack (unchanged) ───────────────┐
│  db → poller → api → local T1 (still works standalone on the LAN,    │
│                        no internet required)                         │
└───────────────────────────┬────────────────────────────────────────┘
                             │  outbound only, on a timer —
                             │  nothing ever connects inbound to a station
                             ▼
                     Cloud Hub (new)
        ┌─────────────────────────────────────────────┐
        │  Ingest API   — receives pushed data,        │
        │                 authenticated by station      │
        │                 device credential              │
        │  Cloud DB     — mirrored data, tagged by      │
        │                 station_id, plus customers/   │
        │                 users/assignments/sessions     │
        │  App API      — T1 + T2 + T3 endpoints, all   │
        │                 served from the cloud DB       │
        └─────────────────────────────────────────────┘
                             ▲
                             │  auth'd session
              T2 (login, /) → T3 (admin, /admin)
              T1 (reused component code, now cloud-served,
                  scoped to whichever station is selected)
```

## Sync cadence — decoupled from the on-site poll rate

The station's local poll interval (currently configurable, independently of this) stays whatever it's set to on-site — that's the live, LAN-fast data the station's own T1 shows locally. The cloud sync is a separate, slower cadence: **default every 30 minutes**, not after every poll. Reasoning: the cloud copy doesn't need to be real-time to be useful for remote/combined viewing, and a longer interval means less to push, less to fail, and less noise if the link is flaky. Made configurable per station rather than hardcoded, in case some customer wants tighter cloud freshness later.

## Repo / deployment layout

New code goes in a new **`cloud/`** folder alongside the existing `api/`, `poller/`, `frontend/`, `config/` — its own `cloud-api/` and `cloud-frontend/` (T1+T2+T3 all served by one app API, per the diagram above), with its own `docker-compose.cloud.yml`.

This gives a clean seam without slowing down the prototype phase: right now, since you're both the only station *and* the one temporarily hosting the cloud hub, you can run both compose files on the same box (`docker compose -f docker-compose.yml -f docker-compose.cloud.yml up`) and it behaves like one system. Later, when HTS hosts the real cloud hub, the `cloud/` folder is the entire deliverable that moves — no code changes, just a different box and a real domain instead of the temporary DDNS one. The existing per-station repo/deploy stays exactly what gets installed at each new customer site.

## New local component: sync

A new small service in the station stack (recommend its own container — a hung outbound push shouldn't affect on-site polling, same reasoning as keeping API and poller separate):

- Watches for rows written since the last successful sync checkpoint (readings, deliveries, prices, poll_log, tank edits).
- Pushes them to the cloud Ingest API in batches on the configured interval (default 30 min), authenticated with the station's device credential.
- Retries with backoff if the cloud is unreachable; buffers locally in Postgres so nothing is lost — it just catches up whenever connectivity returns.
- Only ever dials out. Never listens for anything, never needs a known address.

This makes five containers per station going forward instead of four. Worth being deliberate about that since it's the same question raised for the current four — it earns its own container on the same isolation logic, but it's your call if that changes later.

## Two separate credential types

1. **Station device credential** (machine-to-machine). Station ID + secret, issued by an admin in T3 when a station is provisioned, entered into that station's local settings. Used only by the sync service to authenticate pushes to the Ingest API. Replaces the current `device_id` field, which today is just a self-generated display value with no real auth behind it — it needs to become a credential the cloud actually issues and recognizes, not one the station invents.
2. **User login** (human). Email + password into T2.

Rotating/revoking one never touches the other.

## Auth: session duration + revocation

At login, offer the user a choice of how long to stay signed in:

- Default (short-lived, e.g. until the session ends)
- 90 days ("remember me")
- **Never expires** — an explicit option, since it was asked for

Because "never expires" plus "an admin can revoke it anytime" together rule out a pure stateless JWT (you can't invalidate one early without a blocklist, which is just a worse version of a session table), the natural implementation is a DB-backed `sessions` table: token (stored hashed), user_id, created_at, expires_at (nullable = unlimited), revoked_at (nullable), last_used_at. Every request checks the session is neither expired nor revoked. T3 gets a per-user sessions view where an admin can revoke one session or all of a user's sessions immediately, regardless of what expiry was chosen at login. Worth showing device/browser + last-seen on that list so an admin revoking something can tell what they're actually killing.

## Cloud DB schema (sketch)

- `customers` — id, name, plan info if this ever needs billing
- `stations` — id, customer_id, name, device_id, device_secret_hash, last_sync_at
- `users` — id, email, password_hash, role (`admin` / `user`)
- `user_station_assignments` — user_id, station_id
- `sessions` — id, user_id, token_hash, created_at, expires_at (nullable), revoked_at (nullable), last_used_at
- Mirrored per-station data — same shape as the existing local tables (`readings`, `delivery_events`, `fuel_prices`, `poll_log`, `tanks`), each with a `station_id` column added for tenant scoping. The local schema doesn't need that column; the cloud copy does.

## Combined stats across stations

Same problem `/api/stats/summary` already solved for combining tanks within one station — loop over the relevant entities, call the same per-entity stats function, combine the results, stay modular regardless of count. T2's combined page is that pattern one level up: loop over a user's assigned stations instead of a station's active tanks.

## Build order

1. **Cloud DB + Ingest API + sync service.** Get data flowing outbound and landing correctly, no user-facing UI yet. Prove this part first since everything else depends on it.
2. **T3 admin portal.** Provision customers, stations, users; assign users to stations; issue/rotate station device credentials; manage sessions.
3. **T2 login + station picker + combined stats**, including the session-duration choice and revocation plumbing.
4. **Re-point T1 at the cloud App API**, scoped per station (e.g. `/api/stations/{id}/...`) with an auth header, instead of the flat local `/api/...` it calls today. Should be a mostly mechanical change to `client.js` — the components themselves shouldn't need to change.

## Open questions still worth settling

1. **Local LAN access stays fully functional without cloud, by design** — recommended, and worth stating as a deliberate product commitment rather than a technical accident, precisely because the architecture *could* be flipped to cloud-only pretty easily (station stack has no dependency on the cloud existing at all — the sync service is purely additive). Whether local-only access is ever gated behind a subscription is a business decision, not a technical one, at that point — flagging so it's a conscious choice later, not a surprise.
2. **Sync interval default of 30 minutes** — confirmed direction, exact number and whether it's per-station-configurable in T3 (recommend yes) still to nail down.
3. **One-way sync only for v1** — station pushes to cloud, cloud never pushes commands/config back down. Recommend yes for now; remote settings changes from the cloud side (poll interval, tank capacity, etc.) can be a v2 problem once the read path is solid.
4. **Where the cloud hub lives today** — self-hosted at Raffi's house temporarily until HTS takes over. The `cloud/` folder split above is specifically so that move is just "run this elsewhere," not a rebuild.

# License Server

A database of passphrases you (Raffi) hand out — that's the whole design.
Every Cloud Utility phones home to `/license/check` on startup and
periodically thereafter; there's no offline verification, no signing
keys, no license files to generate or lose.

Runs under the `license` Compose profile (see repo root `docker-compose.yml`).
Not split into its own repo yet, per Raffi's "develop everything together
for now" note — it's a separate deployable *service* within this monorepo,
which is what actually matters for the eventual split.

## How it works

- You create a **License** with `POST /admin/licenses`, choosing the
  passphrase text yourself (e.g. `GARDENA-2026`) — not auto-generated,
  since this is a hand-issued system, not self-serve.
- Each license has a **use limit** (`max_uses`, default 1 — how many
  different Cloud Utility instances may activate with it) and a **fixed
  expiry date set at creation** (`valid_days`, default 365; omit for
  never-expires).
- The **master passphrase** (`PermissionGranted200` by default, override
  via `MASTER_PASSPHRASE`) is auto-seeded on first boot with unlimited
  uses and no expiry — works out of the box, no admin call needed.
- "1-time use" and "phones home every day" coexist via a small
  redemption record: activating (a new Cloud Utility instance's first
  successful check) consumes one use; every check after that from the
  *same* instance is just a routine re-check and doesn't consume another.
  See `models.py`'s docstring for the mechanics.

## Endpoints

### Public-ish (no admin token) — the phone-home call

- `POST /license/check` — body `{"passphrase": "...", "instance_id": "..."}`.
  `instance_id` is a random token the Cloud Utility generates once for
  itself and persists — this is what lets the server tell "same instance
  checking in again" apart from "a different instance trying to activate."
  Returns `{"status": "valid" | "invalid", "customer_name", "station_scope", "expires_at", "detail"}`.
- `GET /health`

### Admin (`X-Admin-Token: <your admin token>`)

- `GET /admin/licenses` — list every code: passphrase, customer, uses
  assigned/used, status, issued/expires, first-redeemed, last-checked.
- `POST /admin/licenses` — create. Body: `{"passphrase", "customer_name", "station_scope"?, "max_uses"? (default 1, omit/null for unlimited), "valid_days"? (default 365, omit/null for never-expires)}`.
- `POST /admin/licenses/{id}/renew` — Body: `{"extend_days"? (default 365)}`. Extends from the current expiry (or now, if already lapsed).
- `POST /admin/licenses/{id}/status` — Body: `{"status": "active" | "suspended"}`.
- `DELETE /admin/licenses/{id}/redemptions/{instance_id}` — free up one use
  (e.g. a decommissioned instance) without touching the license's
  expiry/status. That instance's own copy of the code just stops working
  on its next check.

## Examples

```bash
# Issue a 1-use, 1-year code
curl -X POST http://localhost:8200/admin/licenses \
  -H "X-Admin-Token: $LICENSE_SERVER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"passphrase": "GARDENA-2026", "customer_name": "Gardena Sinclair", "max_uses": 1, "valid_days": 365}'

# See what's out there
curl http://localhost:8200/admin/licenses -H "X-Admin-Token: $LICENSE_SERVER_ADMIN_TOKEN"

# Suspend one
curl -X POST http://localhost:8200/admin/licenses/2/status \
  -H "X-Admin-Token: $LICENSE_SERVER_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"status": "suspended"}'
```

(`$LICENSE_SERVER_ADMIN_TOKEN` here is the *plaintext* token you chose —
export it in your own shell; it's never stored in plaintext on the server
itself, see Key management below.)

## Key management

- `LICENSE_SERVER_ADMIN_TOKEN_HASH` — gates all `/admin/*` routes.
  Required; the service returns 503 on admin routes if it isn't set
  (fails loud, not open). This is a **hash** (SHA-256), not the token
  itself — generate it with `python3 hash_secret.py`. The plaintext token
  only ever exists in your own hands (put it in a password manager) and in
  the `X-Admin-Token` header on each request.
- Passphrases themselves are stored as-is (not hashed) in the `licenses`
  table — they're reusable codes you look up and hand out again if
  needed, not one-time secrets, so there's nothing to gain from hashing
  them, unlike the admin token above.

## Storage

SQLite file at `/data/license-server.db` (mount a volume). This service
will never see meaningful write volume — phone-home checks are reads
(after the first activation), and issuance is a handful of admin-triggered
writes — so there's no Postgres container for it. Swap `DATABASE_URL` to a
Postgres DSN later if that assumption ever stops holding; nothing else
here is SQLite-specific.

## What this deliberately does NOT do

- No customer-facing UI or self-serve signup — internal tool only.
- No offline verification, no signing keys, no license files — every
  check is a live phone-home. This is a conscious simplification over the
  original spec's "Unlimited = no phone-home, ever" design; see
  `docs/licensing-and-updates.md` for the tradeoff.
- Never contacted by a Local Instance, under any circumstance.

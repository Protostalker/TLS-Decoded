# License Server

Small standalone service, per `tls-fuel-platform-strategy.md` / the dev
handoff doc: issues and validates **Annual** licenses (phone-home) and
generates signed **Unlimited** license files (one-off, offline activation).
Only the Cloud Utility ever talks to this — the Local Instance never does,
period.

Runs under the `license` Compose profile (see repo root `docker-compose.yml`).
Not split into its own repo yet, per Raffi's "develop everything together
for now" note — it's a separate deployable *service* within this monorepo,
which is what actually matters for the eventual split.

## Endpoints

### Public-ish (no admin token)

- `POST /license/check` — Annual phone-home. Body: `{"license_key": "..."}`.
  Returns `{"status": "valid" | "invalid" | "grace", "customer_name", "station_scope", "expires_at", "renewed_at", "detail"}`.
- `GET /license/public-key` — PEM public key used to verify Unlimited license
  files offline. Configure this as `LICENSE_SIGNING_PUBLIC_KEY` on every
  Cloud Utility that might activate an Unlimited license.
- `GET /health`

### Admin (`X-Admin-Token: <your admin token>`)

- `GET /admin/licenses/annual` — list.
- `POST /admin/licenses/annual` — issue. Body: `{"customer_name", "station_scope"?, "valid_days"? (default 365)}`.
  Response includes `license_key` **once** — deliver it to the customer, it is never shown again.
- `POST /admin/licenses/annual/{id}/renew` — Body: `{"extend_days"? (default 365)}`.
- `POST /admin/licenses/annual/{id}/status` — Body: `{"status": "active" | "suspended"}`.
- `GET /admin/licenses/unlimited` — list (issuance log only — file itself isn't stored server-side).
- `POST /admin/licenses/unlimited` — **additionally requires** `X-Unlimited-Passphrase`
  (your chosen passphrase — see Key management below for how it's stored).
  Body: `{"customer_name", "station_scope"?}`. Response includes `license_file` — a
  signed JWT with no `exp` claim — deliver it to the customer to paste into their
  Cloud Utility's Admin -> License page (or, at initial deployment only, set via
  `CLOUD_LICENSE_FILE`/`CLOUD_LICENSE_FILE_PATH` — see the Cloud Utility's env example).

## Example: issue an Annual license

```bash
curl -X POST http://localhost:8200/admin/licenses/annual \
  -H "X-Admin-Token: $LICENSE_SERVER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Gardena Sinclair", "station_scope": "up to 3 stations"}'
```

## Example: issue an Unlimited license

```bash
curl -X POST http://localhost:8200/admin/licenses/unlimited \
  -H "X-Admin-Token: $LICENSE_SERVER_ADMIN_TOKEN" \
  -H "X-Unlimited-Passphrase: $UNLIMITED_LICENSE_PASSPHRASE" \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Example Fuel Co"}'
```

(`$LICENSE_SERVER_ADMIN_TOKEN` / `$UNLIMITED_LICENSE_PASSPHRASE` here are the
*plaintext* secrets you chose — export them in your own shell before running
these, they are never stored in plaintext on the server itself; see below.)

## Key management

- `LICENSE_SIGNING_PRIVATE_KEY_PATH` — where the RSA signing key lives (mounted
  volume, `/data/license-signing-key.pem` by default in the Docker image).
  Auto-generated on first boot if missing. **Back this file up** — losing it
  invalidates every Unlimited license issued so far, since Cloud Utility
  installs verify against the matching public key and there's no way to
  reissue the *same* key.
- Rotation: generate a new key, point `LICENSE_SIGNING_PRIVATE_KEY_PATH` at it,
  redeploy, and update `LICENSE_SIGNING_PUBLIC_KEY` on every Cloud Utility
  install going forward. Licenses signed with the OLD key keep validating on
  any Cloud Utility that still trusts the old public key — there is
  deliberately no revocation channel for Unlimited licenses (no phone-home,
  by design), so treat a rotation as "new key for new licenses," not as
  invalidating old ones, unless you also push a new public key everywhere.
- `LICENSE_SERVER_ADMIN_TOKEN_HASH` — gates all `/admin/*` routes. Required;
  the service returns 503 on admin routes if it isn't set (fails loud, not
  open). This is a **hash** (SHA-256) of your admin token, not the token
  itself — generate it with `python3 hash_secret.py --type admin-token`.
  The plaintext token only ever exists in your own hands (put it in a
  password manager) and in the `X-Admin-Token` header on each request.
- `UNLIMITED_LICENSE_PASSPHRASE_HASH` — gates Unlimited issuance
  specifically, on top of the admin token. Also a **hash** (bcrypt, since
  this is a human-chosen phrase rather than a random token) — generate it
  with `python3 hash_secret.py --type passphrase`. Leaving this unset falls
  back to a hash of the dev default (`PermissionGranted200`, per Raffi's
  original answer) — fine for local dev, since that phrase is already
  public (it's in this repo's history); set your own before issuing a real
  license. Neither `.env`/`.env.cloud` nor `docker inspect` ever expose a
  usable plaintext secret — only something an incoming header's hash can be
  checked against. See `hash_secret.py` and `auth.py`'s module docstring
  for the full reasoning.

## Storage

SQLite file at `/data/license-server.db` (mount a volume). This service will
never see meaningful write volume — Annual phone-homes are reads, and
issuance is a handful of admin-triggered writes — so there's no Postgres
container for it. Swap `DATABASE_URL` to a Postgres DSN later if that
assumption ever stops holding; nothing else here is SQLite-specific.

## What this deliberately does NOT do

- No customer-facing UI or self-serve signup — internal tool only, per the
  dev handoff doc ("doesn't need to be customer-facing").
- No revocation channel for Unlimited licenses — that's the sold feature
  (no phone-home, ever), not an oversight.
- Never contacted by a Local Instance, under any circumstance.

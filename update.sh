#!/usr/bin/env bash
# Pull the latest code and rebuild/restart whatever's currently enabled via
# COMPOSE_PROFILES in .env. Safe to run any time — .env and
# config/tls-decoded.yaml are gitignored, so a pull never touches your real
# config, and the Postgres volumes aren't touched by a rebuild either.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

git pull
docker compose up -d --build

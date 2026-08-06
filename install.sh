#!/usr/bin/env bash
# TLS-Decoded installer — interactive, re-runnable.
#
# Asks what kind of deployment this box is, generates secrets on first run
# (and lets you keep or rotate them on later runs), writes .env and
# config/tls-decoded.yaml, sets the docker compose profile(s) that control
# which services actually start, and optionally brings the stack up.
#
# Safe to re-run any time — every answer defaults to your current .env
# value, so hitting Enter through the whole thing just reconfirms what's
# already there. Nothing here touches your database or historical readings.
#
# Usage:  ./install.sh
#
# Built by Healthcare Tech Solutions — healthcaretechsolutions.org
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE=".env"
YAML_FILE="config/tls-decoded.yaml"
YAML_EXAMPLE="config/tls-decoded.yaml.example"

BOLD=$(tput bold 2>/dev/null || true)
DIM=$(tput dim 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)
BLUE=$(tput setaf 4 2>/dev/null || true)
GREEN=$(tput setaf 2 2>/dev/null || true)
YELLOW=$(tput setaf 3 2>/dev/null || true)

say()   { echo -e "${1-}"; }
head1() { echo; echo -e "${BOLD}${BLUE}== $1 ==${RESET}"; }
ok()    { echo -e "${GREEN}✓${RESET} $1"; }
warn()  { echo -e "${YELLOW}!${RESET} $1"; }

# ── Load any existing .env so re-runs default to current values ────────────
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source <(grep -v '^\s*#' "$ENV_FILE" | grep '=' || true)
  set +a
  FIRST_RUN=false
else
  FIRST_RUN=true
fi

# ── Prompt helpers ───────────────────────────────────────────────────────────
# ask VAR "Question" "default"  -> sets VAR, printing the current/default as
# the fallback shown in [brackets]; blank input keeps it.
ask() {
  local __var="$1" __question="$2" __default="${3-}"
  local __current="${!__var:-$__default}"
  local __answer
  if [ -n "$__current" ]; then
    read -rp "$__question [${__current}]: " __answer
  else
    read -rp "$__question: " __answer
  fi
  printf -v "$__var" '%s' "${__answer:-$__current}"
}

ask_secret() {
  # Like ask(), but generates a random value if there's no current one and
  # the user hits Enter, instead of leaving it blank.
  local __var="$1" __question="$2" __bytes="${3:-24}"
  local __current="${!__var:-}"
  local __shown="${__current:+<already set — Enter to keep>}"
  __shown="${__shown:-<Enter to auto-generate>}"
  local __answer
  read -rp "$__question [$__shown]: " __answer
  if [ -n "$__answer" ]; then
    printf -v "$__var" '%s' "$__answer"
  elif [ -z "$__current" ]; then
    printf -v "$__var" '%s' "$(openssl rand -hex "$__bytes")"
    ok "Generated a new ${__var}."
  else
    printf -v "$__var" '%s' "$__current"
  fi
}

ask_yn() {
  local __var="$1" __question="$2" __default="${3:-n}"
  local __hint="y/N"; [ "$__default" = "y" ] && __hint="Y/n"
  local __answer
  read -rp "$__question [$__hint]: " __answer
  __answer="${__answer:-$__default}"
  case "$__answer" in
    y|Y|yes|Yes) printf -v "$__var" 'y' ;;
    *)           printf -v "$__var" 'n' ;;
  esac
}

say ""
say "${BOLD}${BLUE}TLS-Decoded installer${RESET}"
say "${DIM}Built by Healthcare Tech Solutions — healthcaretechsolutions.org${RESET}"
if [ "$FIRST_RUN" = false ]; then
  say "${DIM}Existing .env found — every answer below defaults to what's already set.${RESET}"
fi

# ── Deployment mode ───────────────────────────────────────────────────────
head1 "Deployment mode"
say "  1) Local station        — this box runs the station + its own local dashboard"
say "  2) Cloud server         — this box is the cloud hub only (no station hardware here)"
say "  3) Poll-sync station    — station data pipeline runs and pushes to a remote cloud,"
say "                            but this box's own local dashboard stays OFF"
say "  4) Complete / demo      — everything on one box: station + local dashboard + cloud hub"
MODE=""
CURRENT_PROFILES="${COMPOSE_PROFILES:-}"
case "$CURRENT_PROFILES" in
  station-core,station-ui) DEFAULT_MODE=1 ;;
  cloud)                   DEFAULT_MODE=2 ;;
  station-core)             DEFAULT_MODE=3 ;;
  station-core,station-ui,cloud) DEFAULT_MODE=4 ;;
  *)                        DEFAULT_MODE=1 ;;
esac
read -rp "Choose 1-4 [${DEFAULT_MODE}]: " MODE
MODE="${MODE:-$DEFAULT_MODE}"

case "$MODE" in
  1) COMPOSE_PROFILES="station-core,station-ui"; WANT_STATION=y; WANT_UI=y; WANT_CLOUD=n ;;
  2) COMPOSE_PROFILES="cloud";                    WANT_STATION=n; WANT_UI=n; WANT_CLOUD=y ;;
  3) COMPOSE_PROFILES="station-core";             WANT_STATION=y; WANT_UI=n; WANT_CLOUD=n ;;
  4) COMPOSE_PROFILES="station-core,station-ui,cloud"; WANT_STATION=y; WANT_UI=y; WANT_CLOUD=y ;;
  *) warn "Unrecognized choice '$MODE' — defaulting to Local station."; MODE=1
     COMPOSE_PROFILES="station-core,station-ui"; WANT_STATION=y; WANT_UI=y; WANT_CLOUD=n ;;
esac
ok "Mode: COMPOSE_PROFILES=${COMPOSE_PROFILES}"

# ── Station secrets/ports (station-core or station-ui) ──────────────────────
if [ "$WANT_STATION" = y ]; then
  head1 "Station database & API"
  ask_secret DB_PASSWORD "Station DB password"
  ask_secret SECRET_KEY "API session secret key" 32

  head1 "Station ports"
  ask_yn OVERRIDE_STATION_PORTS "Override any default station ports? (only needed if they collide with something already running on this box)" n
  if [ "$OVERRIDE_STATION_PORTS" = y ]; then
    ask DB_PORT "  Postgres host port" "${DB_PORT:-5432}"
    ask API_PORT "  API host port" "${API_PORT:-8000}"
    [ "$WANT_UI" = y ] && ask FRONTEND_PORT "  Dashboard host port" "${FRONTEND_PORT:-5005}"
  fi

  # config/tls-decoded.yaml holds station name/address/gauge IP — poll
  # interval, alignment, device ID, and tank sizes are DB-backed and
  # editable live from the dashboard either way, so this file mainly
  # matters on first run. Skip re-asking these on a re-run that's keeping
  # the existing file, rather than asking then throwing the answers away.
  WRITE_YAML=y
  if [ -f "$YAML_FILE" ]; then
    ask_yn WRITE_YAML "config/tls-decoded.yaml already exists — regenerate it (station name/address/gauge IP)? Tank sizes/poll interval are editable live from the dashboard regardless." n
  fi

  if [ "$WRITE_YAML" = y ]; then
    head1 "Tank gauge network"
    say "The StarTech (or similar) serial-to-Ethernet adapter's IP — set a DHCP"
    say "reservation on your router for its MAC so this doesn't drift."
    ask_yn USE_MOCK "No gauge hardware connected right now — run against mock/demo data instead?" n
    if [ "$USE_MOCK" = y ]; then
      TLS_MOCK="true"
      TLS_HOST="192.168.0.250"
      TLS_PORT="5000"
      ok "Mock mode — no real gauge needed. Flip network.mock to false in config/tls-decoded.yaml once hardware is connected."
    else
      TLS_MOCK="false"
      ask TLS_HOST "  Gauge adapter IP" "192.168.0.250"
      ask TLS_PORT "  Gauge adapter port" "5000"
    fi

    head1 "Station details"
    ask STATION_NAME "  Station name" "My Station"
    ask STATION_ADDRESS "  Address" "Street, City, ST ZIP"
    ask STATION_PHONE "  Phone" "555-555-5555"
  fi
fi

# ── Cloud sync — only relevant if the station pipeline is running ──────────
if [ "$WANT_STATION" = y ]; then
  head1 "Cloud sync (optional)"
  say "Push this station's data to a cloud hub for remote/multi-station viewing."
  say "This can always be turned on, off, or repointed later — with no restart —"
  say "from the local dashboard's Settings -> Cloud sync panel instead of here."
  ask_yn SETUP_CLOUD_SYNC "Configure cloud sync now? (needs a device credential from your cloud admin — Admin -> Stations -> Provision)" n
  if [ "$SETUP_CLOUD_SYNC" = y ]; then
    ask CLOUD_INGEST_URL "  Cloud ingest URL (e.g. http://your-cloud-host:8100)" "${CLOUD_INGEST_URL:-}"
    ask STATION_DEVICE_ID "  Device ID (from the cloud admin panel)" "${STATION_DEVICE_ID:-}"
    ask STATION_DEVICE_SECRET "  Device secret (shown once at provisioning)" "${STATION_DEVICE_SECRET:-}"
    ask SYNC_INTERVAL_MINUTES "  Sync interval, minutes" "${SYNC_INTERVAL_MINUTES:-30}"
  else
    CLOUD_INGEST_URL="${CLOUD_INGEST_URL:-}"
    STATION_DEVICE_ID="${STATION_DEVICE_ID:-}"
    STATION_DEVICE_SECRET="${STATION_DEVICE_SECRET:-}"
    SYNC_INTERVAL_MINUTES="${SYNC_INTERVAL_MINUTES:-30}"
    say "  Skipped — configure later from the dashboard whenever you have a credential."
  fi
fi

# ── Cloud hub ────────────────────────────────────────────────────────────────
if [ "$WANT_CLOUD" = y ]; then
  head1 "Cloud hub"
  ask_secret CLOUD_DB_PASSWORD "Cloud DB password"
  ask CLOUD_ADMIN_EMAIL "  Bootstrap admin email (creates the first T3 admin account on first boot)" "${CLOUD_ADMIN_EMAIL:-you@example.com}"
  ask_secret CLOUD_ADMIN_PASSWORD "  Bootstrap admin password" 12

  head1 "Cloud hub ports"
  ask_yn OVERRIDE_CLOUD_PORTS "Override any default cloud ports?" n
  if [ "$OVERRIDE_CLOUD_PORTS" = y ]; then
    ask CLOUD_DB_PORT "  Cloud Postgres host port" "${CLOUD_DB_PORT:-5433}"
    ask CLOUD_API_PORT "  Cloud API host port" "${CLOUD_API_PORT:-8100}"
    ask CLOUD_FRONTEND_PORT "  Cloud portal host port" "${CLOUD_FRONTEND_PORT:-5100}"
  fi
fi

# ── Write .env ────────────────────────────────────────────────────────────
head1 "Writing configuration"
{
  echo "# Generated/updated by install.sh — re-run it any time to change these."
  echo "COMPOSE_PROFILES=${COMPOSE_PROFILES}"
  echo ""
  if [ "$WANT_STATION" = y ]; then
    echo "# ── Station ──────────────────────────────────────────────────────────────"
    echo "DB_PASSWORD=${DB_PASSWORD}"
    echo "SECRET_KEY=${SECRET_KEY}"
    [ -n "${DB_PORT:-}" ] && echo "DB_PORT=${DB_PORT}"
    [ -n "${API_PORT:-}" ] && echo "API_PORT=${API_PORT}"
    [ -n "${FRONTEND_PORT:-}" ] && echo "FRONTEND_PORT=${FRONTEND_PORT}"
    echo ""
    echo "# ── Cloud sync (station side) ────────────────────────────────────────────"
    [ -n "$CLOUD_INGEST_URL" ] && echo "CLOUD_INGEST_URL=${CLOUD_INGEST_URL}"
    [ -n "$STATION_DEVICE_ID" ] && echo "STATION_DEVICE_ID=${STATION_DEVICE_ID}"
    [ -n "$STATION_DEVICE_SECRET" ] && echo "STATION_DEVICE_SECRET=${STATION_DEVICE_SECRET}"
    echo "SYNC_INTERVAL_MINUTES=${SYNC_INTERVAL_MINUTES}"
    echo ""
  fi
  if [ "$WANT_CLOUD" = y ]; then
    echo "# ── Cloud hub ────────────────────────────────────────────────────────────"
    echo "CLOUD_DB_PASSWORD=${CLOUD_DB_PASSWORD}"
    echo "CLOUD_ADMIN_EMAIL=${CLOUD_ADMIN_EMAIL}"
    echo "CLOUD_ADMIN_PASSWORD=${CLOUD_ADMIN_PASSWORD}"
    [ -n "${CLOUD_DB_PORT:-}" ] && echo "CLOUD_DB_PORT=${CLOUD_DB_PORT}"
    [ -n "${CLOUD_API_PORT:-}" ] && echo "CLOUD_API_PORT=${CLOUD_API_PORT}"
    [ -n "${CLOUD_FRONTEND_PORT:-}" ] && echo "CLOUD_FRONTEND_PORT=${CLOUD_FRONTEND_PORT}"
    echo ""
  fi
} > "$ENV_FILE"
ok "Wrote $ENV_FILE"

# ── Write config/tls-decoded.yaml (station only) ────────────────────────────
# WRITE_YAML was already decided above, alongside the questions it needs —
# avoids asking station-detail questions and then throwing them away.
if [ "$WANT_STATION" = y ]; then
  if [ "$WRITE_YAML" = y ]; then
    cat > "$YAML_FILE" <<YAML
# Generated/updated by install.sh — re-run it any time to change these.
# Poll interval, alignment, device ID, and tank capacity/reorder-threshold
# are all editable live from the dashboard (gear icon) once running; the
# values below are just the first-run defaults.

station:
  name: "${STATION_NAME}"
  address: "${STATION_ADDRESS}"
  phone: "${STATION_PHONE}"
  station_id: "000000"
  tanks:
    - id: 1
      name: "Unleaded"
      capacity_gallons: 12000
      product: "Unleaded"
      reorder_threshold_gallons: 2000
    - id: 2
      name: "Super"
      capacity_gallons: 12000
      product: "Super"
      reorder_threshold_gallons: 1500
    - id: 3
      name: "Diesel"
      capacity_gallons: 12000
      product: "Diesel"
      reorder_threshold_gallons: 1500

network:
  host: "${TLS_HOST}"
  port: ${TLS_PORT}
  timeout_seconds: 5
  mock: ${TLS_MOCK}

polling:
  mode: "interval"
  interval_minutes: 60
  schedule_times: []

analytics:
  consumption_window_hours: 168
  delivery_detection_jump_gallons: 200

remote:
  enabled: false
  server_url: ""
  device_id: ""
YAML
    ok "Wrote $YAML_FILE"
    say "  ${DIM}Tank names/capacities above are a starting template — correct them any time from Settings once the dashboard is up.${RESET}"
  else
    say "  Kept existing $YAML_FILE untouched."
  fi
fi

# ── Bring it up ───────────────────────────────────────────────────────────
head1 "Done"
say "Profiles active: ${BOLD}${COMPOSE_PROFILES}${RESET}"
ask_yn BRING_UP "Run 'docker compose up -d --build' now?" y
if [ "$BRING_UP" = y ]; then
  docker compose up -d --build
  say ""
  ok "Stack is coming up."
  [ "$WANT_UI" = y ] && say "  Station dashboard:  http://localhost:${FRONTEND_PORT:-5005}"
  [ "$WANT_STATION" = y ] && say "  Station API docs:   http://localhost:${API_PORT:-8000}/docs"
  [ "$WANT_CLOUD" = y ] && say "  Cloud portal:        http://localhost:${CLOUD_FRONTEND_PORT:-5100}"
  [ "$WANT_CLOUD" = y ] && say "  Cloud API docs:      http://localhost:${CLOUD_API_PORT:-8100}/docs"
else
  say "Skipped. Run ${BOLD}docker compose up -d --build${RESET} whenever you're ready."
fi

say ""
say "${DIM}Re-run ./install.sh any time to change deployment mode, rotate secrets,"
say "or reconfigure ports — it's non-destructive to your data either way.${RESET}"
say "${DIM}Support: Healthcare Tech Solutions — healthcaretechsolutions.org — (818) 473-9155${RESET}"

@echo off
REM Pull the latest code and rebuild/restart whatever's currently enabled
REM via COMPOSE_PROFILES in .env. Safe to run any time - .env and
REM config\tls-decoded.yaml are gitignored, so a pull never touches your
REM real config, and the Postgres volumes aren't touched by a rebuild.
cd /d "%~dp0"

git pull
docker compose up -d --build

pause

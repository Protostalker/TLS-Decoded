FROM python:3.11-slim

WORKDIR /app

# curl — python:3.11-slim doesn't include it, but the Compose healthcheck
# below needs it (otherwise the container reports "unhealthy" forever even
# though the app itself is fine).
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite DB lives here — mount a volume at /data in compose so the license
# list (and each code's redemption history) survives a rebuild.
RUN mkdir -p /data
ENV DATABASE_URL=sqlite:////data/license-server.db

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

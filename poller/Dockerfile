FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]

# ── Development target ────────────────────────────────────────────
FROM base AS development
RUN pip install --no-cache-dir watchdog
CMD ["python", "-u", "main.py"]

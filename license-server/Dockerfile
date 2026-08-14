FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite DB lives here — mount a volume at /data in compose so the license
# list (and each code's redemption history) survives a rebuild.
RUN mkdir -p /data
ENV DATABASE_URL=sqlite:////data/license-server.db

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

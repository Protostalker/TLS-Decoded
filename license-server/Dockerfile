FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite DB + signing key live here — mount a volume at /data in compose so
# both survive a rebuild (losing the signing key invalidates every
# previously-issued Unlimited license; losing the DB loses Annual license
# records, though customers can be re-issued a key if that ever happens).
RUN mkdir -p /data
ENV DATABASE_URL=sqlite:////data/license-server.db
ENV LICENSE_SIGNING_PRIVATE_KEY_PATH=/data/license-signing-key.pem

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

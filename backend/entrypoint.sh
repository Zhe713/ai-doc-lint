#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] waiting for PostgreSQL..."
python - <<'PY'
import os, time, sys
import psycopg
dsn = (
    f"host={os.getenv('POSTGRES_HOST', 'db')} port={os.getenv('POSTGRES_PORT', '5432')} "
    f"dbname={os.getenv('POSTGRES_DB', 'ai_doc_lint')} user={os.getenv('POSTGRES_USER', 'aidoc')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'aidoc_local_pwd')} connect_timeout=3"
)
for i in range(60):
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        print("[entrypoint] PostgreSQL is ready")
        sys.exit(0)
    except Exception as exc:
        print(f"[entrypoint] db not ready ({i+1}/60): {exc}")
        time.sleep(2)
print("[entrypoint] PostgreSQL wait timeout")
sys.exit(1)
PY

echo "[entrypoint] running alembic migrations..."
alembic upgrade head

echo "[entrypoint] starting API (gunicorn + uvicorn worker)..."
exec gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "${GUNICORN_WORKERS:-2}" \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -

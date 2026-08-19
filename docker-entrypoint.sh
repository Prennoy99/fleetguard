#!/usr/bin/env sh
# Waits for Postgres to accept connections, seeds it if empty (idempotent —
# safe to run on every container start), then hands off to uvicorn. Needed
# because a sidecar Postgres in the same Container Apps pod has no health-
# check ordering guarantee against the main container, and a fresh/ephemeral
# Postgres data dir starts out with no schema or rows at all.
set -eu

echo "waiting for postgres..."
for i in $(seq 1 30); do
  if python -c "
import sys, psycopg2, os
try:
    psycopg2.connect(os.environ['DATABASE_URL']).close()
except Exception:
    sys.exit(1)
"; then
    echo "postgres is up"
    break
  fi
  sleep 2
done

NEEDS_SEED=$(python -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
try:
    cur.execute(\"SELECT to_regclass('public.telemetry_raw')\")
    exists = cur.fetchone()[0] is not None
    if not exists:
        print('yes')
    else:
        cur.execute('SELECT count(*) FROM telemetry_raw')
        print('yes' if cur.fetchone()[0] == 0 else 'no')
finally:
    conn.close()
")

if [ "$NEEDS_SEED" = "yes" ]; then
  echo "database empty — seeding..."
  python -m generator.generate
else
  echo "database already seeded, skipping"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000

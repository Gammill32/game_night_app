#!/bin/sh
set -e

echo "Waiting for database to be ready..."
python3 - <<'EOF'
import os, sys, time
import urllib.parse

database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

# Parse the database URL
parsed = urllib.parse.urlparse(database_url)
host = parsed.hostname
port = parsed.port or 5432
user = parsed.username
dbname = parsed.path.lstrip("/")

import socket
max_attempts = 30
for attempt in range(max_attempts):
    try:
        sock = socket.create_connection((host, port), timeout=1)
        sock.close()
        print(f"Database is reachable at {host}:{port}")
        break
    except (socket.error, socket.timeout):
        print(f"Attempt {attempt + 1}/{max_attempts}: waiting for {host}:{port}...")
        time.sleep(1)
else:
    print(f"ERROR: Database at {host}:{port} not reachable after {max_attempts} attempts")
    sys.exit(1)
EOF

echo "Running database migrations..."
flask db upgrade

echo "Starting gunicorn..."
# -w 1: Single worker required — APScheduler runs in-process and must not be duplicated
exec gunicorn -w 1 -b 0.0.0.0:8000 "app:create_app()"

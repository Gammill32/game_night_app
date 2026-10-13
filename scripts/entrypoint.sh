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

# The compose game_night_scheduler service runs this image with "scheduler" as
# its command: just the daily reminder job, no web server. It leaves migrations
# to the web container (two containers upgrading at once would race).
if [ "$1" = "scheduler" ]; then
    echo "Starting the reminder scheduler..."
    exec python -m app.scheduler
fi

echo "Running database migrations..."
flask db upgrade

echo "Starting gunicorn..."
# One worker process with 4 threads (gthread): requests no longer queue behind
# one slow one (a photo upload, an email), and in-process state (the BGG
# cache, the session files) is still shared by everything. The web container
# sets ENABLE_SCHEDULER=false; if it doesn't, the reminder job still runs only
# once because there is one process. Don't raise -w without that setting.
exec gunicorn -w 1 -k gthread --threads 4 -b 0.0.0.0:8000 "app:create_app()"

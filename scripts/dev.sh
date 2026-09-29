#!/bin/sh
# Run a command in the dev tooling container against this checkout, e.g.
#   scripts/dev.sh pytest
#   scripts/dev.sh ruff check .
#   scripts/dev.sh flask db migrate -m "add x"
# Expects a throwaway Postgres on 127.0.0.1:55433 (see docs/developer-guide.md).
set -e
cd "$(dirname "$0")/.."
if ! docker image inspect game_night_dev >/dev/null 2>&1; then
  tar c requirements.txt requirements-dev.txt scripts/Dockerfile.dev | docker build -q -t game_night_dev -f scripts/Dockerfile.dev -
fi
exec docker run --rm -i --network host --user "$(id -u):$(id -g)" \
  -v "$PWD":/app -w /app \
  -e HOME=/tmp -e FLASK_APP=app -e FLASK_DEBUG=1 -e ENABLE_SCHEDULER=false \
  -e SECRET_KEY=dev-only -e SESSION_TYPE=filesystem -e MEDIA_DIR=/tmp/media \
  -e DATABASE_URL="${DATABASE_URL:-postgresql://gamenight:gamenight@127.0.0.1:55433/gamenight_dev}" \
  -e TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql://gamenight:gamenight@127.0.0.1:55433/gamenight_test}" \
  game_night_dev "$@"

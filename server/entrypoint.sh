#!/bin/sh
set -e

# Only the API container sets RUN_MIGRATIONS=1, so migrations run exactly once
# on startup; the worker waits behind the same schema without racing on it.
if [ "$RUN_MIGRATIONS" = "1" ]; then
  echo "Running database migrations..."
  alembic upgrade head
fi

exec "$@"

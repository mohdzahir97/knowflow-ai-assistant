#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Starting API server..."
# --no-server-header: uvicorn appends its own "server: uvicorn" banner after
# the application responds, so it cannot be overridden from middleware. The
# application sets a neutral Server header itself.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8001}" --no-server-header

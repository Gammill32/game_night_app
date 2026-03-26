#!/bin/sh
set -e

echo "Running database migrations..."
flask db upgrade

echo "Starting gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:8000 "app:create_app()"

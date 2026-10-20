#!/bin/sh
# Waits for PostgreSQL, then (for the web container only) runs migrations,
# creates the platform tenant and collects static files.
set -e

echo "Waiting for PostgreSQL..."
until pg_isready -d "$DATABASE_URL" -q; do
  sleep 1
done

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "Migrating shared (public) schema..."
  python manage.py migrate_schemas --shared --noinput
  echo "Migrating tenant schemas..."
  python manage.py migrate_schemas --tenant --noinput
  python manage.py bootstrap_platform
  python manage.py sync_roles
  python manage.py sync_licences
  python manage.py collectstatic --noinput
fi

exec "$@"

#!/usr/bin/env bash
# Starts Anish1989 Business OS with Docker on macOS or Linux.
# Usage: ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "== Anish1989 Business OS =="

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker, then run this script again." >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "Creating .env with random local passwords..."
  secret=$(openssl rand -hex 40)
  dbpw=$(openssl rand -hex 16)
  sed -e "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=${secret}|" \
      -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${dbpw}|" \
      -e "s|^DATABASE_URL=.*|DATABASE_URL=postgres://businessos:${dbpw}@db:5432/businessos|" \
      .env.example > .env
else
  echo ".env already exists, keeping it."
fi

if ! grep -Eq '^VAULT_MASTER_KEYS=[^[:space:]]+' .env; then
  echo "Creating the secret vault master key..."
  key="k1:$(openssl rand -base64 32)"
  if grep -q '^VAULT_MASTER_KEYS=' .env; then
    sed -i.bak "s|^VAULT_MASTER_KEYS=.*|VAULT_MASTER_KEYS=${key}|" .env && rm -f .env.bak
  else
    printf '\nVAULT_MASTER_KEYS=%s\n' "$key" >> .env
  fi
  echo "IMPORTANT: back up the VAULT_MASTER_KEYS line from .env (for example in a password manager)."
fi

if ! grep -Eq '^BACKUP_ENCRYPTION_KEYS=[^[:space:]]+' .env; then
  echo "Creating the backup encryption key..."
  key="b1:$(openssl rand -base64 32)"
  if grep -q '^BACKUP_ENCRYPTION_KEYS=' .env; then
    sed -i.bak "s|^BACKUP_ENCRYPTION_KEYS=.*|BACKUP_ENCRYPTION_KEYS=${key}|" .env && rm -f .env.bak
  else
    printf '\nBACKUP_ENCRYPTION_KEYS=%s\n' "$key" >> .env
  fi
  echo "IMPORTANT: back up the BACKUP_ENCRYPTION_KEYS line from .env too. Without it, backups cannot be opened."
fi

echo "Pulling images (first time can take a few minutes)..."
docker compose pull --ignore-pull-failures
echo "Starting services..."
docker compose up -d

echo "Waiting for the platform to become healthy..."
for _ in $(seq 1 60); do
  if curl -fs http://localhost:8000/health/ >/dev/null; then
    echo
    echo "Platform is running."
    echo "  Health:          http://localhost:8000/health/"
    echo "  Platform admin:  http://localhost:8000/admin/"
    echo
    echo "Create the Super Admin (you type the password):"
    echo "  docker compose exec web python manage.py createsuperuser"
    echo "Stop: docker compose down   (your data is kept)"
    exit 0
  fi
  sleep 3
done

echo "The platform did not become healthy in time. Recent logs:" >&2
docker compose ps
docker compose logs --tail 40 web
exit 1

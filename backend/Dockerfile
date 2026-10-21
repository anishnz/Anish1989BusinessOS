# Two stages:
#   1. "frontend-build" builds the React staff app (frontend/) with Node.
#   2. The Python image runs Django and serves that built app at /app/.
# The frontend folder arrives as a second build context called "frontend-src"
# (docker-compose.yml and CI pass it with additional_contexts / build-contexts).

# Node 24 LTS on Debian 12. npm ci installs the exact versions in package-lock.json.
FROM node:24-bookworm-slim AS frontend-build
WORKDIR /frontend
COPY --from=frontend-src package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=frontend-src index.html tsconfig.json vite.config.ts ./
COPY --from=frontend-src src/ src/
RUN npm run build

# Python 3.13 on Debian 12 (bookworm). The minor version and OS release are pinned
# so every build uses the same base. Python packages come from a lock file with hashes.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# PostgreSQL 16 client tools (pg_isready, pg_dump, pg_restore) for backups. Debian 12's own
# postgresql-client is version 15, and pg_dump refuses to copy a newer server, so they come
# from the official PostgreSQL apt repository (key checked against its published fingerprint).
ARG PG_MAJOR=16
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /tmp/pgdg.asc \
    && gpg --show-keys --with-colons /tmp/pgdg.asc | grep -q "^fpr:*B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8:" \
    && gpg --dearmor -o /usr/share/keyrings/pgdg.gpg /tmp/pgdg.asc \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-${PG_MAJOR} \
    && apt-get purge -y gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/pgdg.asc \
    && pg_dump --version | grep -q " ${PG_MAJOR}\."

WORKDIR /app

# base.lock for production images, dev.lock for development images.
COPY requirements/ requirements/
ARG REQUIREMENTS=base.lock
RUN pip install --require-hashes --no-deps -r requirements/${REQUIREMENTS}

COPY . .

# The built React app. Django serves index.html at /app/ and collectstatic
# copies the rest to /static/app/.
COPY --from=frontend-build /frontend/dist /opt/frontend-dist
ENV FRONTEND_DIST=/opt/frontend-dist

# The user guide chapters and pictures (docs/user-guide), shown inside the app at /guide/.
# They arrive as a third build context called "guide-src".
COPY --from=guide-src . /opt/guide
ENV GUIDE_DIR=/opt/guide

# Make the entrypoint work even if it was checked out with Windows line endings.
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

# Run as a non-root user.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/staticfiles /app/media /app/backups \
    && chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]

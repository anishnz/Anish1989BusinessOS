# Python 3.13 on Debian 12 (bookworm). The minor version and OS release are pinned
# so every build uses the same base. Python packages come from a lock file with hashes.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# postgresql-client provides pg_isready and pg_dump (needed for backups later).
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# base.lock for production images, dev.lock for development images.
COPY requirements/ requirements/
ARG REQUIREMENTS=base.lock
RUN pip install --require-hashes --no-deps -r requirements/${REQUIREMENTS}

COPY . .

# Make the entrypoint work even if it was checked out with Windows line endings.
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

# Run as a non-root user.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]

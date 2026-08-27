# UMD API / Worker image (Plan E, P2-S1).
#
# One image, two roles (API server and Hatchet-backed worker), selected by the
# container COMMAND (UMD_ROLE). The image NEVER embeds API secrets: all
# configuration is injected at runtime via environment / Docker secrets / a
# mounted .env — the Dockerfile contains zero credential values or variables
# carrying them. Build-time only installs the pinned test-verified dependency
# set; no creation keys, no tokens.
#
# Note: this image copies the source tree and installs the pyproject dependency
# pins. Container builds are performed in CI/registry (not available in the
# local dev sandbox), so this Dockerfile is a deliverable that is validated
# statically by tests and by CI, not by a local `docker build`.
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Non-root runtime user: sandboxes the container process itself.
RUN groupadd --system umd && useradd --system --gid umd --home /app umd \
    && mkdir -p /app && chown -R umd:umd /app

WORKDIR /app

# Install dependencies first (better layer caching). pyproject pins every
# runtime dependency; the lock manifest is deploy/pins/runtime.txt.
COPY pyproject.toml ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN pip install --no-cache-dir .

# Migrations ship in the image; they execute against the runtime DSN at startup
# (see docker-entrypoint.sh) — never baked into an offline schema image whose
# freshness could silently diverge from a live database.
USER umd

EXPOSE 8080

# Runtime role entrypoint: applies migrations (opt-in via
# UMD_RUN_MIGRATIONS_ON_START=1) then execs the configured server/worker.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]
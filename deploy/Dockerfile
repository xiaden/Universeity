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
    && mkdir -p /app /data/ocfl \
    && chown -R umd:umd /app /data

WORKDIR /app

# Install dependencies first (better layer caching). pyproject pins every
# runtime dependency; the lock manifest is deploy/pins/runtime.txt.
COPY pyproject.toml ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
# Event payload schemas ship in the image so the installed worker/API package can
# resolve schemas/events via UMD_EVENT_SCHEMAS_ROOT (the ancestor-walk fallback only
# works for a repo checkout, not for the installed site-packages copy).
COPY schemas ./schemas
ENV UMD_EVENT_SCHEMAS_ROOT=/app/schemas/events
RUN pip install --no-cache-dir .

# Migrations ship in the image; they execute against the runtime DSN at startup
# (see docker-entrypoint.sh) — never baked into an offline schema image whose
# freshness could silently diverge from a live database.
USER umd

EXPOSE 8080

# Runtime role entrypoint: applies migrations (opt-in via
# UMD_RUN_MIGRATIONS_ON_START=1) then execs the configured server/worker.
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["api"]

# ---------------------------------------------------------------------------
# Worker image (P3-S2): the API role stays lean (base runtime deps only); the
# worker role installs the pinned OPT-IN `.[worker]` extra (hatchet-sdk==1.38.1)
# and smoke-tests the SDK import WITHOUT promoting the candidate pair. Hatchet
# is a GATED dependency: the SDK<->server pair remains CANDIDATE/PENDING live
# validation (deploy/pins/runtime.txt) — installing it here does not promote it.
# The base-image/provider/security boundaries, immutable source/tool provenance,
# and explicit optional capability statuses are preserved (no new secrets, no
# privileged posture, no base dependency change). Compose's `worker` and
# `sandbox-runner` services select this target via `build.target: worker`.
# ---------------------------------------------------------------------------
FROM runtime AS worker
USER root
RUN pip install --no-cache-dir ".[worker]" \
    && python -c "import hatchet_sdk; print('hatchet_sdk import OK (CANDIDATE pair, pending live validation)')"
USER umd
CMD ["worker"]
# syntax=docker/dockerfile:1
# =========================================================================
# Experimently API image.
#
# Build context is the REPOSITORY ROOT (the code imports `backend.app.*`):
#
#   docker build -f backend/Dockerfile -t experimently-api:ce .
#   docker build -f backend/Dockerfile --target ee -t experimently-api:ee .
#
# Targets:
#   ce  (default) community edition — backend/ only
#   ee  enterprise edition — additionally copies ee/ when the directory exists
#
# Runtime contract:
#   ENTRYPOINT backend/docker-entrypoint.sh  (waits for Postgres, bootstraps the
#              schema when RUN_MIGRATIONS=true, applies SEED=... once)
#   CMD        uvicorn backend.app.main:app --workers ${WEB_CONCURRENCY:-1}
#   HEALTHCHECK GET /health/live
# =========================================================================

ARG PYTHON_VERSION=3.11

# -------------------------------------------------------------------------
# Stage 1: builder — resolve and install the runtime dependency set into a venv
# -------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# gcc + libc headers: a few pins (psutil on arm64) have no binary wheel and
# build from source; libpq-dev for psycopg2 headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
        linux-libc-dev \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements/runtime.txt /tmp/runtime.txt
RUN pip install --upgrade pip && pip install -r /tmp/runtime.txt

# -------------------------------------------------------------------------
# Stage 2: runtime — the minimal application image both editions share
# -------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG BUILD_DATE
ARG GIT_COMMIT
ARG EDITION=ce

LABEL org.opencontainers.image.title="Experimently API" \
      org.opencontainers.image.description="FastAPI backend for the Experimently experimentation platform" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      io.experimently.edition="${EDITION}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    EXPERIMENTLY_EDITION=${EDITION} \
    WEB_CONCURRENCY=1 \
    PORT=8000

# libpq5: psycopg2 runtime; postgresql-client: pg_isready for the entrypoint;
# curl: HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Application code. The layout under /app mirrors the repository so that
# `backend.app.main:app`, `python -m backend.app.db.bootstrap` and the seed
# scripts resolve exactly as they do from a checkout.
COPY --chown=appuser:appgroup backend/ /app/backend/
RUN chmod +x /app/backend/docker-entrypoint.sh \
    && mkdir -p /data/demo \
    && chown -R appuser:appgroup /data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD curl -fsS http://localhost:${PORT:-8000}/health/live || exit 1

ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# -------------------------------------------------------------------------
# Stage 3: ee — runtime plus the enterprise package (`--target ee`).
#
# `ee/` does not exist in the community checkout. `COPY ee* /app/ee/` uses a
# glob so the build does not fail when the directory is absent (a glob that
# matches nothing is tolerated by COPY, an explicit path is not); the
# `ee/requirements.txt` install is likewise guarded.
# -------------------------------------------------------------------------
FROM runtime AS ee

ARG EDITION=ee
ENV EXPERIMENTLY_EDITION=ee
LABEL io.experimently.edition="ee"

USER root
COPY --chown=appuser:appgroup ee* /app/ee/
RUN if [ -f /app/ee/requirements.txt ]; then \
        pip install --no-cache-dir -r /app/ee/requirements.txt; \
    else \
        echo "ee/ not present in build context; image is functionally CE"; \
    fi
USER appuser

# -------------------------------------------------------------------------
# Stage 4: ce — the community image. Last stage = default target, so a plain
# `docker build -f backend/Dockerfile .` produces CE.
# -------------------------------------------------------------------------
FROM runtime AS ce
ENV EXPERIMENTLY_EDITION=ce
LABEL io.experimently.edition="ce"

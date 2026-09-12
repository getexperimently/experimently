# syntax=docker/dockerfile:1
# =========================================================================
# Experimently dashboard image.
#
#   docker build -f frontend/Dockerfile -t experimently-web:ce .
#
# The build context is the REPOSITORY ROOT (like backend/Dockerfile): the
# in-app documentation pages (/docs/*) are rendered at build time from the
# markdown under docs/, which lives next to frontend/, not inside it.
#
# Stage 1 builds the Next.js static export (output: 'export' -> out/) and
# generates the nginx location blocks for the dynamic routes from
# .next/routes-manifest.json. Stage 2 serves it with nginx-unprivileged on
# port 8080 and proxies /api/, /ws/ and /health* to API_UPSTREAM (default
# http://api:8000), so the browser talks to a single origin and the API base
# baked into the bundle can stay empty (NEXT_PUBLIC_API_URL="").
# =========================================================================

ARG NODE_VERSION=22

# -------------------------------------------------------------------------
# Stage 1: build
# -------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS builder

WORKDIR /app/frontend

ENV NEXT_TELEMETRY_DISABLED=1 \
    CI=true

# Full install: next build needs typescript, tailwindcss, postcss,
# autoprefixer, all of which are devDependencies.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# src/pages/docs/[...slug].tsx reads ../docs relative to the frontend dir.
COPY docs/ /app/docs/

# Relative API base by default: nginx proxies /api/ to the backend. Pass an
# absolute URL only when the dashboard is served from a different origin.
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build \
    && test -f .next/routes-manifest.json \
    && node scripts/nginx-routes.mjs --out /app/nginx/routes.conf \
    && test -d out \
    # The docs pages must have found the markdown; a placeholder means the
    # docs/ copy above is missing.
    && ! grep -rl "Documentation coming soon" out/docs >/dev/null

# -------------------------------------------------------------------------
# Stage 2: serve
# -------------------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

ARG BUILD_DATE
ARG GIT_COMMIT
LABEL org.opencontainers.image.title="Experimently Dashboard" \
      org.opencontainers.image.description="Static Next.js dashboard served by nginx, proxying /api to the Experimently API" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${GIT_COMMIT}"

ENV API_UPSTREAM=http://api:8000

USER root
# The unprivileged image ships a default server on 8080; ours replaces it via
# the template rendered by docker-entrypoint.sh.
RUN rm -f /etc/nginx/conf.d/default.conf \
    && mkdir -p /etc/nginx/templates \
    && chown -R nginx:nginx /etc/nginx/conf.d /etc/nginx/templates
COPY --chown=nginx:nginx frontend/nginx.conf /etc/nginx/templates/default.conf.template
COPY --chown=nginx:nginx frontend/docker-entrypoint.sh /usr/local/bin/experimently-entrypoint.sh
COPY --from=builder --chown=nginx:nginx /app/nginx/routes.conf /etc/nginx/experimently-routes.conf
COPY --from=builder --chown=nginx:nginx /app/frontend/out /usr/share/nginx/html
RUN chmod +x /usr/local/bin/experimently-entrypoint.sh
USER nginx

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/usr/local/bin/experimently-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]

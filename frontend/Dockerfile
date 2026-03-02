# syntax=docker/dockerfile:1
# =========================================================
# Stage 1: Dependencies
# =========================================================
FROM node:18-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --only=production

# =========================================================
# Stage 2: Builder
# =========================================================
FROM node:18-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

# =========================================================
# Stage 3: Static file server (nginx)
# =========================================================
FROM nginx:1.25-alpine AS runtime

# Security: non-root nginx user
RUN addgroup -g 1001 appgroup && \
    adduser -u 1001 -G appgroup -s /bin/sh -D appuser

# Copy static build output
COPY --from=builder /app/out /usr/share/nginx/html

# Custom nginx config for SPA routing
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:80/health.html || exit 1

CMD ["nginx", "-g", "daemon off;"]

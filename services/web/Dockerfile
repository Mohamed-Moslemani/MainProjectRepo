# ── Stage 1: build the Vite SPA ────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

# Install deps first (cached layer when package.json is unchanged)
COPY services/web/package.json services/web/package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Copy source and build
COPY services/web/ ./

# VITE_API_URL is baked in at build time. For a single-origin production
# deployment behind nginx (Day 3 of the prod-ready sprint), override with
# --build-arg VITE_API_URL="" so API calls stay same-origin.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=${VITE_API_URL}
# Optional: GlitchTip / Sentry DSN baked at build time. Empty
# disables error capture (the init in main.jsx is a no-op when DSN
# is unset).
ARG VITE_SENTRY_DSN=
ENV VITE_SENTRY_DSN=${VITE_SENTRY_DSN}

RUN npm run build

# ── Stage 2: serve the static bundle via nginx ─────────────────────────────
FROM nginx:1.27-alpine

COPY services/web/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# Basic healthcheck — index.html must be reachable via the container itself
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ > /dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]

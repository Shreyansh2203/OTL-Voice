# OTL Timesheet Assistant — single-origin image.
# Stage 1 builds the PWA; stage 2 runs the FastAPI backend, which serves the
# built frontend/dist itself (one origin). Put nginx in front for TLS (see
# deploy/docker-compose.yml).

# ---------- Stage 1: build the PWA ----------
FROM node:22-slim AS frontend
WORKDIR /fe
# Install deps first for better layer caching
COPY pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json ./frontend/package.json
RUN npm install -g pnpm@12.6.0 && pnpm install --frozen-lockfile
COPY frontend/ ./frontend/
WORKDIR /fe/frontend
RUN ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build

# ---------- Stage 2: backend runtime ----------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    FRONTEND_DIST=/app/frontend/dist

WORKDIR /app

# curl: container HEALTHCHECK.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --frozen --no-cache --no-dev --no-install-project

# Put the uv venv on the path so uvicorn is found
ENV PATH="/opt/venv/bin:$PATH"

# Backend code (carries db/schema.sql and db/seed.json), then the built SPA.
COPY backend ./backend
COPY --from=frontend /fe/frontend/dist ./frontend/dist

# The reference database is created and seeded on first startup. Mount a volume
# here to keep employees and assignments across container replacements.
RUN mkdir -p /app/data

# Switch to a non-root user for security best practices
RUN groupadd --gid 10001 appgroup && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appgroup /app
USER appuser

VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

# --proxy-headers / --forwarded-allow-ips: trust X-Forwarded-* from nginx so the
# app sees the real client scheme/IP (needed for correct behaviour behind TLS).
CMD ["uvicorn", "backend.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]

FROM node:26.9.0-slim@sha256:3a771f83944bb763050c23c0225c260638c4b7899e7a72485ef75e5e570499e5 AS frontend

ENV PNPM_HOME=/pnpm
ENV PATH=/pnpm:$PATH
WORKDIR /fe
RUN npm install --global pnpm@12.6.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json ./frontend/package.json
RUN pnpm install --frozen-lockfile
COPY frontend/ ./frontend/
RUN pnpm --filter otl-timesheet-pwa exec tsc -b tsconfig.app.json tsconfig.node.json \
    && pnpm --filter otl-timesheet-pwa exec vite build

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    FRONTEND_DIST=/app/frontend/dist \
    IDEMPOTENCY_DB_PATH=/app/data/idempotency/idempotency.sqlite3

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

COPY --from=ghcr.io/astral-sh/uv:0.12.14@sha256:1946145b8706ad9e5c0e79a513f9e324b58d5e38126bb2c8b7dbfca61febeb45 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-cache --no-dev --no-install-project
ENV PATH="/opt/venv/bin:/usr/local/bin:${PATH}"

COPY --chown=10001:10001 backend ./backend
COPY --from=frontend --chown=10001:10001 /fe/frontend/dist ./frontend/dist
COPY --chown=10001:10001 deploy/readycheck.py ./deploy/readycheck.py
RUN install -d -o 10001 -g 10001 /app/data /app/data/idempotency

USER 10001:10001
VOLUME ["/app/data", "/app/data/idempotency"]
EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=8s --start-period=30s --retries=3 \
    CMD ["python", "/app/deploy/readycheck.py"]

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

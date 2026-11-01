# Architecture

## Request path

The application is deliberately single-origin. A browser, installed PWA, or Capacitor WebView sends requests to nginx over HTTPS/WSS. Nginx forwards the request to the FastAPI process on the private container network (or to `127.0.0.1:8000` in the host-level Ansible deployment). FastAPI serves both the built PWA and `/api` routes.

```text
client
  -> TLS nginx
    -> FastAPI/uvicorn (UID 10001)
      -> auth/session and CSRF middleware
      -> API routers
        -> OCI GenAI, Speech, and realtime STT clients
        -> Fusion HCM/PPM catalogue and OTL client
      -> SQLite catalogue and idempotency store
```

The Vite development server proxies `/api` to port 8000 so local development has the same cookie and same-site behavior as production.

## Backend boundaries

- `backend/main.py` owns application lifespan, middleware, security headers, static PWA serving, and router registration.
- `backend/api/v1/` contains transport-facing auth, chat/voice, timecard, health, and admin routes.
- `backend/core/` contains session/JWT, CSRF helpers, rate limiting, configuration, and token revocation.
- `backend/services/` contains Fusion/OTL, catalogue, OCI, chat, and timecard domain integrations.
- `backend/schemas/` and `backend/models.py` define transport/domain contracts.
- `backend/tests/` uses mocks and an opt-in live integration module; normal CI never needs live credentials.

The catalogue refresh is asynchronous. Operators must distinguish process liveness (`/api/health`) from a successful dependency probe. The deployment readiness helper can additionally check Redis and an authenticated OTL probe when those settings are supplied.

## Frontend boundaries

- React and TypeScript render the chat, voice, review, history, and authentication views.
- Vite builds the PWA and Workbox service worker. The service worker excludes `/api` from precaching/fallback.
- React Query owns server state; browser APIs own ephemeral UI and voice state.
- The API client uses same-origin `/api` by default and sends cookies. The session cookie is HttpOnly; it is not exposed to application JavaScript.
- Playwright tests mock external API boundaries and run against Chromium, Firefox, and WebKit. They do not prove Oracle/OCI connectivity.

## Persistence

There are two independent persistence concerns:

1. The Fusion catalogue/cache and other local application data live under `/app/data`.
2. The idempotency SQLite store prevents a retried timecard write from creating a duplicate Oracle record. Its configured path is `/app/data/idempotency/idempotency.sqlite3` in the production image.

Both paths must be on persistent storage. Compose declares `app_data` and `idempotency_data` volumes; Ansible creates `/opt/otl-voice/data` and `/opt/otl-voice/idempotency`. A container replacement without those mounts loses the deduplication history and can make a retry unsafe.

SQLite is appropriate for a single deployment volume. For multiple writers or regions, use a shared transactional store or partition ownership; do not point multiple independent containers at a SQLite file on unreliable network storage.

## Trust boundaries

- Nginx is the public TLS boundary. Only nginx should reach the app port on a host deployment.
- The OTL service account is server-to-server identity. It is not an end-user login and must have least privilege.
- OCI credentials are server-side secrets. Browser code receives only application responses and the HttpOnly session cookie.
- The browser is untrusted. It can request only what the authenticated session and CSRF checks allow.
- External AI output is untrusted input to the review/validation layer. It cannot authorize a write by itself; a user must approve the structured review.

## Scaling and failure behavior

- Multiple app replicas should use `REDIS_REQUIRED=true` and a shared Redis endpoint for rate limits/token revocation.
- The image has a read-only root filesystem, bounded `/tmp`, dropped capabilities, and a persistent data mount. It still requires a writable idempotency path.
- OCI/Fusion calls can fail or time out independently. The UI must show a retryable error and preserve the user's review rather than claiming a write succeeded.
- A lost Oracle response is handled through the idempotency store and a stable per-entry request ID. Operators must preserve that store until all in-flight retries have expired.

# OTL Timesheet Assistant

OTL Timesheet Assistant is a voice-first, single-origin web application for recording Oracle Fusion Cloud Time and Labour (OTL) entries. A React/Vite PWA talks to a FastAPI service that authenticates the user, resolves Fusion assignments, streams OCI Generative AI and speech responses, validates a proposed timecard, and submits it only after an explicit review and approval.

The repository is intentionally usable without live Oracle or OCI credentials for unit, container, and browser smoke tests. Live integration tests are opt-in and require a separately provisioned test identity.

## Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Oracle and OCI setup](#oracle-and-oci-setup)
- [Authentication](#authentication)
- [Testing and quality gates](#testing-and-quality-gates)
- [PWA and mobile builds](#pwa-and-mobile-builds)
- [Deployment](#deployment)
- [Security and operations](#security-and-operations)
- [Known limitations](#known-limitations)
- [Documentation map](#documentation-map)

## Architecture

```text
Browser / installed PWA / Capacitor app
                | HTTPS + WSS (one origin)
                v
        nginx TLS reverse proxy
                |
                v
       FastAPI (uvicorn, non-root)
        |          |           |
        v          v           v
   OCI GenAI   OCI Speech   Oracle Fusion HCM/PPM
                             + OTL REST
                |
                v
     SQLite catalogue + idempotency store
```

- `frontend/` contains the React/TypeScript PWA, Workbox service worker, unit tests, and Playwright tests.
- `backend/` contains FastAPI routes, authentication/session middleware, Oracle and OCI clients, validation, and the local catalogue/idempotency services.
- `deploy/` contains the production Compose stack, nginx TLS configuration, Ansible provisioning, readiness checks, and credential preflight.
- `.github/workflows/` contains locked-dependency CI, CodeQL, release-please, GHCR publishing, image scanning, and the Ansible deployment handoff.
- The application serves the built PWA and API from one origin. The browser receives an HttpOnly session cookie; application JavaScript does not need to read the session token.

The catalogue is refreshed in the background and is stored under `/app/data`. Timecard write deduplication is durable when the idempotency SQLite volume is mounted. The production image sets `IDEMPOTENCY_DB_PATH=/app/data/idempotency/idempotency.sqlite3`; the idempotency volume must not be placed on an ephemeral container filesystem.

## Prerequisites

### Required for native development

- Python 3.12 or newer compatible with `pyproject.toml`.
- [`uv`](https://docs.astral.sh/uv/) for Python dependency and lockfile management.
- Node.js 22 and pnpm 12.6.0 (Corepack or the pinned pnpm package is supported).
- Git and a POSIX shell for the repository helper scripts. The Makefile itself uses Python and Docker Compose for portability on Windows, Linux, and macOS.

### Required for container deployment

- Docker Engine with Compose v2.24 or newer.
- A DNS name and a trusted TLS certificate. The production Compose file intentionally has no plaintext-only production listener.
- A persistent Docker volume or host directory for `/app/data` and a second persistent volume/directory for `/app/data/idempotency`.
- A managed Redis endpoint for a multi-instance production deployment (`REDIS_REQUIRED=true`).

### Optional

- Android Studio, Xcode, CocoaPods, and native signing identities for Capacitor builds.
- Ansible and an SSH inventory for the tracked production playbook.
- Oracle Fusion and OCI accounts for live development or integration testing.

## Quick start

### Linux and macOS

```bash
git clone <repository-url>
cd OTL-Voice
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the generated value in `SESSION_SECRET_KEY` and fill in the other values described in [docs/configuration.md](docs/configuration.md). Install dependencies from the canonical workspace lockfile:

```bash
uv sync --locked --all-groups
pnpm install --frozen-lockfile
```

Start the native development processes:

```bash
make dev
```

The Vite server is at `http://127.0.0.1:5173`; its `/api` requests proxy to FastAPI on port 8000. For a local-only Docker stack, use the explicit development file:

```bash
make up-dev
```

The development stack uses `SESSION_COOKIE_SECURE=false` and is not a production deployment.

### Windows PowerShell

```powershell
git clone <repository-url>
Set-Location OTL-Voice
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
uv sync --locked --all-groups
pnpm install --frozen-lockfile
make dev
```

If `make` is not installed, run the equivalent commands directly:

```powershell
uv run python dev_runner.py
```

For Docker Desktop, use `docker compose -f deploy/docker-compose.dev.yml up -d --build`. The production Compose file requires certificates and should not be used as a plaintext convenience stack.

### Credential-free smoke test

The following checks do not call Fusion, OCI, or Redis:

```bash
make smoke
uv run pytest backend/tests
pnpm --dir frontend run test:unit
pnpm --dir frontend run build
make image-check
```

The CI container smoke test sets `TEST_MODE=true` and uses only throwaway values. Never copy CI values into a deployed environment.

## Configuration

Copy `.env.example` to a secret-managed environment file. The template is intentionally not a secret store; do not commit `.env`, PEM files, OCI config files, rendered Compose files containing credentials, or browser exports.

The complete variable reference is in [docs/configuration.md](docs/configuration.md). Important production settings include:

| Setting | Production guidance |
| --- | --- |
| `SESSION_SECRET_KEY` | Random, independently rotated signing secret; never use the example value. |
| `SESSION_COOKIE_SECURE` | `true`. The production Compose and Ansible paths enforce this. |
| `SESSION_COOKIE_SAMESITE` | `lax` or `strict`; `none` also requires secure cookies and a deliberate cross-site design. |
| `OIDC_ISSUER` / `OIDC_AUDIENCE` | OIDC issuer and API audience for enterprise SSO; both must be configured together. |
| `AUTH_USERS` | Per-user scrypt verifier mapping for isolated non-OIDC deployments. |
| `REDIS_REQUIRED` | `true` when more than one app process or node is deployed. |
| `IDEMPOTENCY_DB_PATH` | A path on the persistent idempotency volume. |
| `OTL_BASE_URL` | The HTTPS Fusion HCM Time Recording REST endpoint for the tenant. |
| `OCI_*` | OCI region, compartment, and API-key/profile settings; private keys are mounted or injected by a secret manager. |
| `READINESS_REQUIRE_OTL` | `true` in production so liveness cannot mask an unavailable required OTL dependency. |

Run the non-printing preflight before a production deployment:

```bash
make preflight
```

It reports missing or placeholder variable names and configuration errors, never variable values.

## Oracle and OCI setup

### Oracle Fusion Cloud

1. Identify the Fusion tenant, HCM/OTL REST API version, and the exact HCM and PPM base URLs. The defaults in `.env.example` are examples, not credentials.
2. Ask the Fusion administrator for a dedicated integration service account. Grant only the REST resources and actions the application uses: worker/person lookup, assignment/catalogue reads, timecard reads, timecard create, and timecard delete where the product flow requires it. Do not grant broad administrator roles.
3. Restrict the account to the required business units, legal entities, projects, work orders, tasks, and employee populations. Test with a non-production person and a non-production timecard window.
4. Store the service username/password in the deployment secret manager. Do not put them in the image, Compose YAML, GitHub logs, or an OCI PEM file.
5. Confirm the tenant's API version, time zone, payroll time types, expenditure types, and approval rules with the Fusion administrator. The server-side allowlists and hour limits are configurable safety controls, not a substitute for Oracle configuration.

Validate the connection with a dedicated integration account and the opt-in live test, never with a production write by accident:

```bash
RUN_LIVE_INTEGRATIONS=true LIVE_PERSON_NUMBER=<test-person> uv run pytest backend/tests/test_live_integrations.py
```

### Oracle Cloud Infrastructure

1. Create or select a dedicated compartment.
2. Grant the integration principal access to the Generative AI model and Speech service required by the selected models, plus compartment access for the inference clients. Follow Oracle's current IAM policy names and least-privilege guidance; policy names vary by tenant and service.
3. Prefer an OCI API key profile or workload identity mechanism supported by the deployment platform. If an API key is used, keep the private key outside the repository and inject it through a read-only secret mount.
4. Set the service and model region explicitly, especially when the GenAI and Speech regions differ. Confirm quotas, model availability, request limits, and data-handling requirements.
5. Rotate the OCI key/fingerprint and Fusion service credential independently. A rotation must be tested in a non-production environment before the old credential is revoked.

## Authentication

Production supports two explicit modes selected by configuration (never by a shared fallback password):

- **OIDC:** configure `OIDC_ISSUER` and `OIDC_AUDIENCE` (and optionally `OIDC_JWKS_URL`, algorithms, and claim paths). The frontend submits the provider-issued OIDC JWT as the login credential; the backend validates its signature, issuer, audience, expiry, and person-number claim, then creates a cookie-only API session. The identity provider owns password policy, MFA, lockout, and federation.
- **Per-user scrypt users:** leave OIDC settings empty and configure `AUTH_USERS` as a protected JSON mapping of exact person numbers/usernames to unique scrypt verifiers. The value must be injected as a secret, never committed or reused as a general login password. Password changes and offboarding update the mapping atomically and invalidate active sessions.

The browser uses an HttpOnly, Secure session cookie in production and a readable CSRF token cookie/header pair for state-changing requests. Do not put bearer tokens in localStorage, query strings, screenshots, or logs. The frontend must continue to use `credentials: include` (or the equivalent fetch behavior) so the browser sends the cookie.

`DEV_MODE` and `TEST_MODE` are development/test conveniences. They must not be enabled in production, and they do not replace either production auth mode. See [docs/authentication.md](docs/authentication.md) for the threat model and operational checklist.

## Testing and quality gates

The repository uses locked dependencies and explicit coverage gates:

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check backend
uv run mypy backend
uv run pytest backend/tests --cov=backend --cov-fail-under=65
pnpm install --frozen-lockfile
pnpm --dir frontend run typecheck
pnpm --dir frontend run lint
pnpm --dir frontend exec vitest run --coverage --coverage.thresholds.statements=75 --coverage.thresholds.branches=70
pnpm --dir frontend run build
```

CI additionally typechecks frontend test files and runs the complete Playwright matrix (Chromium, Firefox, and WebKit). Install browsers before a local matrix run:

```bash
pnpm --dir frontend exec playwright install --with-deps chromium firefox webkit
make test-e2e-matrix
```

Coverage reports, Playwright reports, traces, and failure logs are uploaded as GitHub Actions artifacts. Live Oracle/OCI tests are excluded unless `RUN_LIVE_INTEGRATIONS=true` is explicitly set. See [docs/testing.md](docs/testing.md).

## PWA and mobile builds

The web build is an installable PWA. Workbox precaches the application shell but deliberately does not cache `/api`; authentication, assignments, chat, speech, and timecard operations require a network connection.

For a native Capacitor build:

1. Deploy the backend behind HTTPS and obtain a reachable API URL.
2. Set `VITE_API_URL` to the HTTPS API origin before building. Do not use a plaintext mobile URL.
3. Run `pnpm --dir frontend run cap:sync` after a normal web build, or use the guarded mobile target:

   ```bash
   VITE_API_URL=https://otl.example.com pnpm --dir frontend run build:mobile
   ```

4. Open the native project with `pnpm --dir frontend run cap:android` or `pnpm --dir frontend run cap:ios` and configure platform signing, permissions, microphone access, and an HTTPS network security policy.
5. Test microphone permission denial, background/foreground transitions, token expiry, VPN/offline behavior, and an install/update on each supported OS version.

Native signing, store submission, and certificate issuance are intentionally operator-managed. See [docs/mobile.md](docs/mobile.md).

## Deployment

### GHCR image and release flow

- Pull requests and pushes to `main` run CI.
- Release-please creates the release/tag.
- `.github/workflows/image.yml` builds the versioned GHCR image, attaches an SBOM and provenance, and scans the published image. No `:latest` image is published.
- `.github/workflows/cd.yml` is an explicit, protected Ansible deployment handoff. Supply a versioned tag or, preferably, an `@sha256:` image digest. The old Render hook is not part of the deployment path.

### Compose (TLS-first production)

1. Provision `/etc/letsencrypt` (or an equivalent secret store) and copy the certificate to `deploy/nginx/certs/fullchain.pem` and `privkey.pem` on the host. Keep the directory out of Git.
2. Provision the environment file through the secret manager and provide `REDIS_URL` with `REDIS_REQUIRED=true`.
3. Provision a renewable, read-only readiness session token at `deploy/secrets/readiness_token` with UID 10001 read access.
4. Validate without starting services:

   ```bash
   make config
   make preflight
   ```

5. Start the stack:

   ```bash
   OTL_IMAGE=ghcr.io/<owner>/otl-voice:<version> make up
   ```

   Port 80 only redirects to HTTPS; port 443 is the application entrypoint. The app is not published directly.

### Ansible

`deploy/ansible/playbook.yml` is the tracked production target. It installs Docker/nginx, creates persistent data/idempotency directories, validates certificate and environment-file presence, pulls only a versioned/digest-pinned GHCR image, starts a non-root/read-only container, and validates nginx before restart. A minimal inventory is shown in `deploy/ansible/inventory.example`.

### Readiness and smoke checks

`/api/health` is a process/liveness check. The bundled `deploy/readycheck.py` also checks Redis when `REDIS_REQUIRED=true` and, in the production default, calls the authenticated OTL readiness endpoint using a renewable secret-mounted session token (`READINESS_REQUIRE_OTL=true`). This distinction prevents a running process from being mistaken for a fully ready Oracle integration. Keep readiness credentials out of the image and rotate them with the session/probe secret.

## Security and operations

- TLS is terminated at nginx; `SESSION_COOKIE_SECURE=true` is enforced by production manifests.
- The app container runs as UID 10001, drops Linux capabilities, uses a read-only root filesystem, and has bounded temporary storage.
- Session cookies are HttpOnly. CSRF protection, CSP, frame denial, content-type protection, body limits, rate limits, and trusted-proxy configuration are enabled in the application.
- Secrets are injected at runtime. The preflight command intentionally reports names and validity only, never values.
- The idempotency SQLite database is persistent and should be backed up with the application data. Protect it as sensitive operational data.
- See [docs/security.md](docs/security.md) for threat boundaries and [docs/operations.md](docs/operations.md) for incident response and rotation.

## Known limitations

- The PWA is installable but not an offline timesheet queue; API calls always use the network.
- Browser speech recognition may be used as a fallback when the OCI realtime speech path is unavailable; microphone data can then follow the browser vendor's processing path.
- OCI/Fusion availability, quotas, model availability, and tenant-specific API versions remain operational dependencies.
- Redis is required for a multi-process production deployment; an in-memory fallback is not a distributed rate-limit or revocation store.
- The current UI supports the core capture/review/history flow, not every possible Oracle approval, edit, cancellation, payroll, or reporting workflow.
- Native mobile signing, store releases, certificate renewal, and push notifications are not automated by this repository.
- Live integration tests are deliberately opt-in and can create or modify Oracle data; use an isolated tenant and test person.

## Documentation map

- [Architecture](docs/architecture.md)
- [Local development](docs/local-development.md)
- [Configuration](docs/configuration.md)
- [Authentication](docs/authentication.md)
- [Testing](docs/testing.md)
- [Mobile/PWA](docs/mobile.md)
- [Deployment](docs/deployment.md)
- [Security](docs/security.md)
- [Operations and incident response](docs/operations.md)

## Contributing and releases

Use Conventional Commit messages, keep lockfiles synchronized with package manifests, and include tests for behavior changes. CodeQL, Dependabot, release-please, the GHCR publisher, and the Ansible deployment target are part of the supported delivery path. Never include credentials, private keys, session cookies, or raw employee/chat data in an issue, pull request, artifact, or log.

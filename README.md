# OTL Timesheet Assistant

[![CI](https://github.com/Shreyansh2203/OTL-Voice/actions/workflows/ci.yml/badge.svg)](https://github.com/Shreyansh2203/OTL-Voice/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Shreyansh2203/OTL-Voice/actions/workflows/codeql.yml/badge.svg)](https://github.com/Shreyansh2203/OTL-Voice/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688.svg)](https://fastapi.tiangolo.com)
[![React: 19](https://img.shields.io/badge/React-19-61dafb.svg)](frontend/package.json)
[![TypeScript: 5.9](https://img.shields.io/badge/TypeScript-5.9-3178C6.svg)](frontend/package.json)
[![Vite: 6](https://img.shields.io/badge/Vite-6-646CFF.svg)](frontend/vite.config.ts)
[![Docker: GHCR](https://img.shields.io/badge/docker-gHCR-2496ED?logo=docker&logoColor=white)](https://github.com/Shreyansh2203/OTL-Voice/pkgs/container/otl-voice)

## The problem

Recording time in Oracle Fusion Cloud Time and Labour is a form-filling exercise, and
it happens at the worst possible moment: end of shift, on a phone, with the details
scattered across assignment records. Choosing the right project, task, work order, and
expenditure type from a long catalogue is slow and easy to get wrong, and a wrong
entry surfaces days later as a payroll exception or an unpaid shift.

Fusion offers no conversational or voice entry path, and the context needed to fill
the form correctly — which projects and tasks a person is actually assigned to — is
not something the form will look up for you.

## What it does

Ask for the shift in plain language. A React/Vite PWA talks to a FastAPI service that
authenticates the user, resolves their real Fusion assignments, streams an OCI
Generative AI and Speech response, and returns a structured timecard proposal.

Nothing is written to Oracle until you read it and approve it. The proposal is
validated server-side against your assignments, the payroll-time and expenditure-type
allowlists, and the daily and per-entry hour limits before submission, and every write
carries an idempotency key so a retried request cannot create a duplicate timecard.

The app is a single origin: an installable PWA served by the same TLS-terminated
service that holds the API, with an HttpOnly session cookie. The browser never reads
the session token.

The repository is intentionally usable without live Oracle or OCI credentials for unit,
container, and browser smoke tests. Live integration tests are opt-in and require a
separately provisioned test identity.

## Tech stack

| Layer | Technology | Role |
| --- | --- | --- |
| API | FastAPI, Uvicorn, Pydantic | Routes, dependency-injected session resolution, request validation |
| Auth | OIDC (RS256 via JWKS) or per-user scrypt, PyJWT | Two explicit production identity modes, cookie-only sessions, Redis-backed revocation |
| Oracle | `httpx` client for Fusion HCM/PPM REST, OCI SDK for GenAI and Speech | Assignment catalogue, timecard reads/writes, speech-to-text and LLM streaming |
| Storage | SQLite (WAL) for the assignment catalogue and the idempotency store | Durable write deduplication; both volumes are operator-provisioned |
| Rate limiting | `redis.asyncio` with a dev-only in-memory fallback | Per-IP request limits and per-user WebSocket caps |
| Errors | Sentry SDK with credential-scrubbing `before_send`, `before_send_transaction`, and `before_breadcrumb` processors | Sensitive flows dropped entirely; query strings, request bodies, cookies, headers, user/tag identity, the raw ASGI scope, and local variables stripped; breadcrumbs never retained |
| Frontend | React 19, TypeScript 5.9, Vite 6, TanStack Query, Workbox | Voice/text chat, assignment picker, review panel, installable PWA shell |
| Native | Capacitor 8 | Optional iOS and Android shells around the same PWA |
| Quality | Ruff, mypy, pytest + coverage, ESLint, Vitest + coverage, Playwright + axe, CodeQL | Gates enforced in `make verify` and CI |
| Delivery | Docker + GHCR, release-please, Dependabot, Ansible, nginx | Pinned images with SBOM/provenance/Trivy scan, protected production handoff |

## Contents

- [The problem](#the-problem)
- [What it does](#what-it-does)
- [Tech stack](#tech-stack)
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

The catalogue is refreshed in the background and is stored under `/app/data`. Timecard write deduplication is durable when the idempotency SQLite volume is mounted. The production image sets `IDEMPOTENCY_DB_PATH=/app/data/idempotency/idempotency.sqlite3`; the idempotency volume must not be placed on an ephemeral container filesystem. A submission in flight holds a short lease (`IDEMPOTENCY_LEASE_SECONDS`, 120s by default) that keeps a concurrent duplicate out; once that lease expires the claim is reclaimable, so a crashed write cannot block its `requestId` for the whole 24h TTL. See [docs/configuration.md](docs/configuration.md) for the full semantics.

## Prerequisites

### Required for native development

- Python 3.12 or newer compatible with `pyproject.toml`, which declares `requires-python = ">=3.12"`. CI runs the backend suite as a matrix over 3.12 and 3.13, and the container image ships 3.13. Both legs pass on the 1.0.0 baseline; see [docs/testing.md](docs/testing.md#supported-python-range).
- [`uv`](https://docs.astral.sh/uv/) for Python dependency and lockfile management.
- Node.js 24 and pnpm 12.6.0 (Corepack or the pinned pnpm package is supported). CI runs Node 24.
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
make verify          # format, lint, typecheck, backend and frontend unit tests
make coverage        # backend and frontend coverage gates
```

Individual commands, if you want to run one in isolation:

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check backend deploy
uv run mypy backend
uv run pytest backend/tests --cov=backend --cov-report=xml
pnpm install --frozen-lockfile
pnpm --dir frontend run typecheck
pnpm --dir frontend run lint
pnpm --dir frontend exec vitest run --coverage
pnpm --dir frontend run build
```

`make verify` and `make coverage` are the authority on which checks run and what
they currently require; read them rather than copying any number out of this file
into a new place. The backend coverage gate is `fail_under` in
`[tool.coverage.report]` in the root `pyproject.toml`. The frontend Vitest
thresholds live in `frontend/vite.config.ts` under `test.coverage.thresholds` —
read them there, and read the measured percentages out of the coverage table each
run prints. Every raise is earned with tests; excluding code or adding coverage
pragmas to clear a number is not acceptable. See [docs/testing.md](docs/testing.md)
and [CONTRIBUTING.md](CONTRIBUTING.md).

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
- Release-please creates the release/tag. It uses the `simple` strategy and the
  `extra-files` list in `release-please-config.json`, so the released version is
  written to `version.txt`, `package.json`, `frontend/package.json`, and
  `pyproject.toml` together; the changelog path and release-PR title are pinned in
  the same config. The current release is tracked in
  `.release-please-manifest.json` and recorded in [CHANGELOG.md](CHANGELOG.md),
  which is seeded at the `1.0.0` baseline. Do not bump those four files by hand:
  release-please owns them, and a manual bump becomes a conflict in the next
  release PR.
- **The release-to-image path needs a token that is not the default one.**
  release-please currently runs on `GITHUB_TOKEN`, and GitHub suppresses the events
  a `GITHUB_TOKEN` raises — so the release it publishes does not trigger the
  `release: [published]` trigger in `image.yml`, and versioned images only get
  built by a manual dispatch or a manually pushed `v*` tag (both triggers exist).
  To automate it, give release-please a PAT or GitHub App token with `contents:
  write` and `pull-requests: write` via the `token:` input in
  `.github/workflows/release-please.yml`.
- `.github/workflows/image.yml` runs a high/critical image scan on any pull request that can change the image, then builds the versioned GHCR image, attaches an SBOM and provenance, and scans the published image. The publish job is skipped on pull requests (where there is no version to publish). The workflow rejects any tag that is not a semantic version, so no `:latest` image is published.
- `.github/workflows/cd.yml` is an explicit, protected Ansible deployment handoff. Supply a versioned tag or, preferably, an `@sha256:` image digest, and reject `latest` in the same way. The old Render hook is not part of the deployment path.

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
- To report a vulnerability, use the private GitHub advisory channel described in [SECURITY.md](SECURITY.md). Do not open a public issue for one.
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
- [Security policy and reporting](SECURITY.md)
- [Operations and incident response](docs/operations.md)

## Portfolio

Other projects by the same author. Each is a standalone repository with its own scope; only OTL-Voice is described in depth here.

| Repository | What it is |
| --- | --- |
| [OTL-Voice](https://github.com/Shreyansh2203/OTL-Voice) | This project: an installable PWA that logs Oracle Time & Labour hours by chat or voice and submits them to OTL. |
| [oracle-bip-reconciler](https://github.com/Shreyansh2203/oracle-bip-reconciler) | FastAPI service that repairs incoming payment and remittance JSON in place and matches it against invoice and receipt history in Oracle Fusion ERP Cloud BI Publisher. |
| [Product-Comparison-Advisor-AI-Agent](https://github.com/Shreyansh2203/Product-Comparison-Advisor---AI-Agent) | Oracle Fusion Cloud AI Agent configuration that compares two or more Items on curated product and manufacturing attributes and returns an HTML comparison table. |
| [Merge-TIFF](https://github.com/Shreyansh2203/Merge-TIFF) | Next.js web tool that merges multiple TIFF images into one multi-page TIFF through a serverless Python function. |
| [Scraping-Bot](https://github.com/Shreyansh2203/Scraping-Bot) | Telegram bot that downloads the media behind an Instagram or Twitter/X link. |

Each of those repositories links back here from its own README, so either end of a link is a way in.

## Contributing and releases

[CONTRIBUTING.md](CONTRIBUTING.md) covers the commit convention, the quality gates, how to run the suite with and without live credentials, and the security controls a change must not weaken. In short: use Conventional Commit messages, keep lockfiles synchronized with package manifests, and include tests for behavior changes. CodeQL, Dependabot, release-please, the GHCR publisher, and the Ansible deployment target are part of the supported delivery path. Never include credentials, private keys, session cookies, or raw employee/chat data in an issue, pull request, artifact, or log.

# OTL-Voice

<div align="center">

[![Build Status](https://img.shields.io/github/actions/workflow/status/Shreyansh2203/OTL-Voice/ci.yml?branch=main&label=CI&logo=github-actions&style=for-the-badge)](https://github.com/Shreyansh2203/OTL-Voice/actions)
[![CodeQL](https://img.shields.io/github/actions/workflow/status/Shreyansh2203/OTL-Voice/codeql.yml?branch=main&label=CodeQL&logo=github&style=for-the-badge)](https://github.com/Shreyansh2203/OTL-Voice/security/code-scanning)
[![Image Scan](https://img.shields.io/github/actions/workflow/status/Shreyansh2203/OTL-Voice/image.yml?branch=main&label=Image%20Scan&logo=docker&style=for-the-badge)](https://github.com/Shreyansh2203/OTL-Voice/actions/workflows/image.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg?style=for-the-badge)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue?style=for-the-badge&logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-white?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Vite + React](https://img.shields.io/badge/Vite_React-black?style=for-the-badge&logo=vite)](https://vitejs.dev/)

</div>

<details open>
<summary><b>Table of Contents</b></summary>

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Demo Mode](#demo-mode)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Production Go-Live](#production-go-live)
- [Security](#security)
- [Testing](#testing)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

</details>

---

## Overview

**OTL-Voice** is an enterprise voice assistant platform integrating Oracle Fusion Cloud, OCI (Oracle Cloud Infrastructure) AI services, and Redis. It provides a FastAPI backend with a React/Vite frontend, optional mobile clients (Android + iOS via Capacitor), session management, and production-ready provisioning tooling.

Designed for operator provisioning: real deployments require Fusion, OCI, Redis, TLS, and IdP credentials provided by the operator.

---

## Features

| Feature | Description |
|---------|-------------|
| **Dual frontend** | React/Vite web app + Capacitor mobile (Android & iOS) |
| **Oracle Fusion integration** | Catalogue, timecards, assignments, OTL client |
| **OCI AI services** | Generative AI, speech-to-text, real-time speech |
| **Session management** | Redis-backed sessions with `SESSION_SECRET_KEY` / `ADMIN_API_KEY` |
| **Demo mode** | `DEMO_MODE=true` runs without any operator credentials |
| **Secret provisioning** | `deploy/provision.py` generates seeds `.env` without printing secrets |
| **Production preflight** | `deploy/preflight.py --mode production` validates readiness |
| **Structured logging** | Sentry + scoped sensitive-field scrubbing |
| **100%+ test coverage** | 688 backend tests passing, frontend unit + visual tests |
| **Docker-ready** | `deploy/docker-compose.yml` + `start.bat`/`start.sh` |

---

## Tech Stack

<details>
<summary><b>Backend</b></summary>

- [Python 3.12+](https://www.python.org/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [python-dotenv](https://pypi.org/project/python-dotenv/)
- [sentry-sdk](https://docs.sentry.io/platforms/python/)
- [uv](https://github.com/astral-sh/uv) — package management

</details>

<details>
<summary><b>Frontend (Web)</b></summary>

- [Vite](https://vitejs.dev/) + [React](https://react.dev/)
- [TypeScript](https://www.typescriptlang.org/)
- [Tailwind CSS](https://tailwindcss.com/)
- [Playwright](https://playwright.dev/) — E2E + visual tests

</details>

<details>
<summary><b>Mobile</b></summary>

- [Capacitor](https://capacitorjs.com/) — Android + iOS
- Android Studio + Xcode projects included

</details>

<details>
<summary><b>Dev / Security</b></summary>

- [ruff](https://docs.astral.sh/ruff/) — lint + format
- [mypy](http://mypy.readthedocs.io/) — type checking (61 files scoped)
- [pytest](https://docs.pytest.org/) — backend testing (688 passed, 4 skipped)
- [CodeQL](https://codeql.github.com/) — SAST
- [Trivy](https://aquasecurity.github.io/trivy/) — container image scan

</details>

---

## Project Structure

```
OTL-Voice/
├── backend/
│   ├── main.py                 # FastAPI app, /api/health
│   ├── api/v1/                 # auth, chat, tts, stt, otl, timecards
│   ├── core/                   # auth, config, limiter, token blocklist
│   ├── services/               # fusion_catalogue, oci_genai, oci_speech, otl_client
│   └── tests/                  # 688 tests
├── frontend/
│   ├── src/                    # React + Vite source
│   ├── tests/                  # Playwright E2E + unit
│   ├── package.json
│   └── vite.config.ts
├── frontend/android/           # Capacitor Android project
├── frontend/ios/               # Capacitor iOS project
├── deploy/
│   ├── provision.py            # generates secrets, seeds .env (no secret printing)
│   ├── preflight.py            # production readiness gate
│   ├── docker-compose.yml
│   ├── nginx/
│   └── certs/.gitkeep
├── docs/PRODUCTION-CHECKLIST.md
├── pyproject.toml
├── uv.lock
├── start.bat / start.sh
└── LICENSE
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- Node.js + pnpm (frontend)
- Docker (optional, for containerized deploy)

### Backend — Demo Mode (no operator credentials)

```bash
cd OTL-Voice

# Create venv
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install
uv sync

# Run in demo mode
DEMO_MODE=true \
SESSION_SECRET_KEY="synthetic-session-secret-key-0123456789abcdef" \
REDIS_REQUIRED="false" \
ALLOW_IN_MEMORY_SESSIONS="true" \
uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Verify
curl http://127.0.0.1:8000/api/health
# {"status":"ok"}
```

### Frontend

```bash
cd OTL-Voice/frontend
pnpm install
pnpm run dev        # http://localhost:5173
pnpm run build
pnpm run test       # unit + E2E
```

### Docker

```bash
docker compose -f deploy/docker-compose.yml up --build
```

---

## Demo Mode

Set `DEMO_MODE=true` to run without Fusion, OCI, or Redis credentials. Sessions fall back to in-memory storage. This is for evaluation only — **not for production**.

---

## Configuration

### Required (production)

| Variable | Description |
|----------|-------------|
| `SESSION_SECRET_KEY` | Session signing secret (generated by `provision.py`) |
| `ADMIN_API_KEY` | Admin API key (generated by `provision.py`) |
| `FUSION_API_VERSION` | Oracle Fusion API version |
| `OCI_PRIVATE_KEY_PASSPHRASE` | OCI private key passphrase |
| `REDIS_URL` | Redis connection URL |

### Optional tuning (§10 in `.env.example`)

`STRICT_ASSIGNMENT`, `CATALOGUE_REFRESH_SECONDS`, `DEFAULT_START_HOUR`, `DEFAULT_EXPENDITURE_TYPE`, `OTL_TIMEOUT_SECONDS`, and more — see `.env.example` for the full list with defaults.

### Secret provisioning

```bash
cd OTL-Voice/deploy
python provision.py           # generates .env (secrets not printed)
python provision.py --dry-run # validate without writing
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Service health (`{"status":"ok"}`) |
| `/api/auth/*` | POST/GET | Authentication & session management |
| `/api/chat` | POST | Chat with OCI GenAI |
| `/api/tts` | POST | Text-to-speech (OCI) |
| `/api/stt/*` | POST | Speech-to-text (OCI) |
| `/api/otl/*` | GET/POST | Oracle Fusion OTL operations |
| `/api/timecards` | GET/POST | Timecard submission & review |

---

## Production Go-Live

See the operator go-live checklist for the full production readiness steps. Summary:

1. Obtain Fusion / OCI / Redis / TLS / IdP credentials from your operator
2. Run `deploy/provision.py` to generate `.env` (secrets are never printed)
3. Run `deploy/preflight.py --mode production` — must exit `0`
4. Build and deploy `deploy/docker-compose.yml`
5. Place TLS termination + authenticating proxy (IdP) in front

**OTL-Voice cannot deploy to production without real operator provisioning values.** Demo mode is evaluation-only.

---

## Security

| Control | Implementation |
|---------|---------------|
| **Secret generation** | `provision.py` creates `SESSION_SECRET_KEY` / `ADMIN_API_KEY` / `readiness_token` — never printed |
| **Sensitive field scrubbing** | Sentry events scrub `authorization`, `cookie`, `token`, `jwt`, `password`, etc. |
| **Session secrets** | Redis-backed or in-memory (demo only) |
| **SAST** | CodeQL on every push |
| **Container scan** | Trivy image scan in CI |
| **Type safety** | `mypy` on 61 backend files |

---

## Testing

```bash
# Backend (688 passed, 4 skipped — live integrations need RUN_LIVE_INTEGRATIONS)
uv run pytest backend/tests/ -q

# Lint + format
uv run ruff check backend/ deploy/
uv run ruff format --check backend/ deploy/

# Type check (61 files)
uv run mypy backend/

# Frontend
cd frontend
pnpm install
pnpm run test        # unit + E2E + visual
pnpm run build       # production build
```

CI requires: `pytest` pass, `ruff` clean, `mypy` clean, `preflight --mode production` exit 0, `pnpm build` success.

---

## Deployment

| Platform | Target |
|----------|--------|
| **Docker Compose** | `deploy/docker-compose.yml` |
| **Render / Railway** | `render.yaml` + `.env` |
| **Raw** | `uvicorn backend.main:app` |

**Never deploy without:** real Fusion/OCI/Redis/TLS/IdP values, `SESSION_SECRET_KEY`, `ADMIN_API_KEY`, and a passing `preflight --mode production`.

---

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/your-feature`)
3. Run checks: `ruff check`, `ruff format --check`, `mypy backend/`, `pytest backend/tests/`
4. Commit and open a Pull Request

---

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Made with ❤️ by [Shreyansh Srivastava](https://github.com/Shreyansh2203)**

[![GitHub stars](https://img.shields.io/github/stars/Shreyansh2203/OTL-Voice?style=social)](https://github.com/Shreyansh2203/OTL-Voice/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Shreyansh2203/OTL-Voice?style=social)](https://github.com/Shreyansh2203/OTL-Voice/network)

</div>
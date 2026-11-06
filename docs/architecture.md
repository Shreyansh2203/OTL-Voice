# Architecture

## Overview

OTL-Voice is an enterprise voice assistant platform integrating Oracle Fusion Cloud, OCI (Oracle Cloud Infrastructure) AI services, and Redis.

## Components

### Backend (FastAPI + Python 3.12+)
- `/api/health` — Service health
- `/api/auth/*` — Authentication & session management
- `/api/chat` — Chat with OCI GenAI
- `/api/tts` — Text-to-speech (OCI)
- `/api/stt/*` — Speech-to-text (OCI)
- `/api/otl/*` — Oracle Fusion OTL operations
- `/api/timecards` — Timecard submission & review

### Frontend (React + Vite)
- Web app (React 19 + Vite 6 + Tailwind CSS 4)
- Mobile apps (Capacitor: Android + iOS)

### Services
- `fusion_catalogue.py` — Oracle Fusion catalogue client
- `oci_genai.py` — OCI Generative AI
- `oci_speech.py` — OCI speech services
- `otl_client.py` — Oracle Time and Labor client
- `idempotency.py` — Idempotency store

### Deployment
- Docker Compose: `deploy/docker-compose.yml`
- Nginx reverse proxy: `deploy/nginx/otl.conf`
- Secret provisioning: `deploy/provision.py`
- Preflight check: `deploy/preflight.py --mode production`
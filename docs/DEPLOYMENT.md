# Production Deployment & Operations Guide

This runbook details how to build, deploy, configure TLS/SSL, and operate the **OTL Voice Timesheet Assistant** in production container environments.

---

## 1. Container Topology

The application uses a **single-origin architecture** running behind an **Nginx reverse proxy**:

```text
[Internet / Corporate Intranet]
               │
          Port 80 / 443
               ▼
   ┌───────────────────────┐
   │         Nginx         │
   │  (Static Cache + TLS) │
   └───────────┬───────────┘
               │ Internal (:8000)
               ▼
   ┌───────────────────────┐
   │     FastAPI Backend   │
   │  (PWA Static + /api)  │
   └───────────┬───────────┘
               ▼
   ┌───────────────────────┐
   │   /app/data Volume    │
   │      (/app/data)      │
   └───────────────────────┘
```

---

## 2. Multi-Stage Container Build

The [`Containerfile`](../Containerfile) uses two distinct build stages:
1. **Frontend Stage (`node:22-slim`)**: Installs dependencies using `npm ci --legacy-peer-deps --ignore-scripts` (with fallback to `npm install --legacy-peer-deps --ignore-scripts`) and runs `npm run build` to output compiled, hashed assets into `/fe/dist`.
2. **Backend Runtime (`python:3.12-slim`)**: Installs Python dependencies using `uv sync --frozen --no-dev`, copies the backend application code, and mounts the built frontend assets into `/app/frontend/dist`.

---

## 3. Deployment with Docker Compose

### Step 1: Clone Repository & Prepare Directory
```bash
git clone https://github.com/Shreyansh2203/OTL-Voice.git /opt/otl-timesheet
cd /opt/otl-timesheet
```

### Step 2: Configure Environment & Keys
Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
chmod 600 .env
```
Ensure your OCI PEM key is located at the path specified in `deploy/docker-compose.yml` (e.g. `../oci_api_key.pem`).

### Step 3: Build and Start Services
```bash
cd deploy
docker compose up -d --build
```

---

## 4. Windows: Batch Scripts (`start.bat` & `start_container.bat`)

For local Windows workstations with Docker, helper scripts manage the container stack:

- `start.bat`: One-click launcher with built-in pre-flight checks:
  - Validates that the Docker daemon is running (exits with error if not).
  - Validates that the `.env` configuration file exists (exits with error if missing).
  - Starts the stack via `docker compose up -d --build`, waits 5 seconds before opening the browser to `http://localhost`.
- `start_container.bat`: A wrapper script with additional commands:
  | Command | Action |
  | :--- | :--- |
  | `start_container.bat` | Start the stack and attach an interactive shell to the `app` container. |
  | `start_container.bat build` | Force re-build the images and recreate the containers. |
  | `start_container.bat shell` | Open an interactive `bash` shell inside the running `app` container. |
  | `start_container.bat logs` | Follow live container logs (`docker compose logs -f`). |
  | `start_container.bat status` | Display container runtime state. |
  | `start_container.bat stop` | Stop the stack without removing it. |
  | `start_container.bat remove` | Stop and remove the stack. |

---

## 5. Linux/macOS: Makefile & start.sh

For Linux and macOS environments, the repository provides both a one-click launcher and a Makefile:

- `start.sh` — Equivalent one-click launcher for Linux/macOS that validates Docker daemon is running and `.env` exists, starts containers via `docker compose up -d --build`, waits 5 seconds, and opens `http://localhost` in your default browser.
- `Makefile` — Provides standard lifecycle targets:
  | Command | Action |
  | :--- | :--- |
  | `make` or `make up` | Smart start (validates `.env`, runs Docker Compose) |
  | `make build` | Force rebuild |
  | `make down` | Stop and remove containers |
  | `make shell` | Open bash shell in container |
  | `make logs` | Follow live logs |
  | `make status` | Show running service status |

---

## 6. Enabling HTTPS / TLS Certificates

By default, Nginx listens on HTTP port 80. To enable production TLS:

### 1. Place SSL Certificates
Copy your certificate and private key into `deploy/nginx/certs/`:
- `deploy/nginx/certs/fullchain.pem`
- `deploy/nginx/certs/privkey.pem`

### 2. Update `deploy/nginx/otl.conf`
Uncomment the HTTPS server block and update domain names:
```nginx
server {
    listen 443 ssl http2;
    server_name timesheet.yourcompany.com;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://app:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

### 3. Update Environment
In `.env`, set:
```bash
SESSION_COOKIE_SECURE=true
```

Restart the stack:
```bash
docker compose restart
```

---

## 7. Health Probes & Monitoring

The container defines an automated Docker healthcheck probing `/api/health` every 30 seconds:

```bash
docker compose ps
```

Expected output:
```text
NAME           IMAGE               STATUS                   PORTS
deploy-app-1   timesheet-app       Up (healthy)             8000/tcp
deploy-nginx-1 nginx:1.27-alpine   Up                       0.0.0.0:80->80/tcp
```

---

## 8. Backups & Disaster Recovery

The `/app/data` volume is persisted as a named Docker volume (`otl-data`) or bound to `./data`. It is reserved for future local caching or session storage.

---

## 9. Troubleshooting Common Issues

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| **`Docker daemon is not running`** | Docker Desktop or engine not running | Start Docker Desktop (Windows/macOS) or `systemctl start docker` (Linux) before running scripts or `make`. |
| **`.env file is missing`** | Environment file not created | Copy `.env.example` to `.env` and populate required credentials. |
| **`HTTP 500 OtlConfigError`** | Missing `OTL_SERVICE_USERNAME` or `OTL_SERVICE_PASSWORD` | Check `.env` variables and ensure they are populated without surrounding quotes. |
| **`401 Unauthorized` on OTL requests** | Invalid Oracle Fusion HCM service account credentials | Validate credentials against Oracle Fusion using `GET /api/health/otl`. |
| **`OCI Private Key Not Found`** | PEM key file path invalid inside container | Ensure the volume mount in `docker-compose.yml` points to the correct host `.pem` file. |
| **Cookie not saved in browser** | `SESSION_COOKIE_SECURE=true` over unencrypted HTTP | Set `SESSION_COOKIE_SECURE=false` when testing over HTTP without SSL. |

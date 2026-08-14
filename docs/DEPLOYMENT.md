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
1. **Frontend Stage (`node:22-slim`)**: Installs dependencies and runs `npm run build` to output compiled, hashed assets into `/fe/dist`.
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

## 4. Enabling HTTPS / TLS Certificates

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

## 5. Health Probes & Monitoring

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

## 6. Backups & Disaster Recovery

The `/app/data` volume is persisted as a named Docker volume (`otl-data`) or bound to `./data`. It is reserved for future local caching or session storage.

---

## 7. Troubleshooting Common Issues

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| **`HTTP 500 OtlConfigError`** | Missing `OTL_SERVICE_USERNAME` or `OTL_SERVICE_PASSWORD` | Check `.env` variables and ensure they are populated without surrounding quotes. |
| **`401 Unauthorized` on OTL requests** | Invalid Oracle Fusion HCM service account credentials | Validate credentials against Oracle Fusion using `GET /api/health/otl`. |
| **`OCI Private Key Not Found`** | PEM key file path invalid inside container | Ensure the volume mount in `docker-compose.yml` points to the correct host `.pem` file. |
| **Cookie not saved in browser** | `SESSION_COOKIE_SECURE=true` over unencrypted HTTP | Set `SESSION_COOKIE_SECURE=false` when testing over HTTP without SSL. |

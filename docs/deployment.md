# Deployment

## Supported production topology

```text
Internet
   |
   | 443 TLS (port 80 redirects only)
   v
nginx (host or deploy/nginx service)
   |
   | 127.0.0.1:8000 or private Compose network
   v
OTL-Voice container (UID 10001, read-only root)
   |                         |
   | /app/data                | /app/data/idempotency
   v                         v
persistent volume         persistent idempotency volume
```

The application port is never published directly in the Compose production file. The only supported plaintext listener is the explicit `docker-compose.dev.yml` file for local development.

## Image publication

`.github/workflows/image.yml` runs for a version tag, a published release, or manual dispatch. It:

- logs in to GHCR using the workflow token;
- builds the multi-stage image from the root lockfiles;
- publishes a semver tag, release tag, and commit-SHA tag (never `latest`);
- emits an SBOM and provenance attestations through Buildx;
- runs a high/critical Trivy image scan;
- fails the publication on unfixed high/critical findings according to policy.

Use an immutable `@sha256:` reference in Ansible. A human-readable version tag is useful for inventory but a digest is the strongest deployment pin.

## Compose production

### Prerequisites

- Docker Compose v2.24 or newer (the production file uses optional `env_file` entries so configuration validation does not require secrets to be present on a workstation).
- `deploy/nginx/certs/fullchain.pem` and `privkey.pem` with a trusted certificate chain.
- A secret-managed `.env` containing non-placeholder values.
- `REDIS_URL` reachable from the app network when `REDIS_REQUIRED=true`.
- A renewable, read-only OTL readiness session token at `deploy/secrets/readiness_token` (or the Ansible host equivalent).
- Persistent Docker volumes for both data paths.

### Validate and start

```bash
make config
make preflight
OTL_IMAGE=ghcr.io/<owner>/otl-voice@sha256:<digest> make up
```

The production Compose environment forces `SESSION_COOKIE_SECURE=true`, `DEV_MODE=false`, `TEST_MODE=false`, `CSP_DEV_MODE=false`, and `REDIS_REQUIRED=true`. It mounts `app_data` and `idempotency_data`, drops all capabilities, uses a read-only root filesystem, and bounds `/tmp`.

Port 80 returns a redirect to HTTPS. Port 443 is the application entrypoint. The Compose file does not contain a plaintext-only production mode.

### Secret provisioning

Do not put secrets in the Compose file. Use one of these patterns:

- platform secret injection into the container environment;
- a host-managed environment file with mode `0600` mounted/loaded by the runtime;
- a secret manager sidecar/agent that materializes short-lived files.

The application currently reads environment variables, so an operator must ensure the variables are present in the process environment. `env_file` is supported for a host-managed file, but it is not a substitute for platform secret management.

## Ansible deployment

`deploy/ansible/playbook.yml` is the tracked deployment target. It refuses mutable image tags, requires `/opt/otl-voice/.env`, TLS files, and `/opt/otl-voice/secrets/readiness_token`, creates the data/idempotency directories with UID 10001 ownership, installs a restrictive container configuration, and runs `nginx -t` before restarting nginx.

Example inventory:

```bash
cp deploy/ansible/inventory.example deploy/ansible/inventory.ini
ansible-playbook -i deploy/ansible/inventory.ini deploy/ansible/playbook.yml \
  -e 'otl_image=ghcr.io/<owner>/otl-voice@sha256:<digest>'
```

The host must already contain the environment file, readiness token, and certificate material at the paths checked by the playbook. Keep the environment file, token, and private key out of Git. The playbook intentionally does not create credentials or certificate issuance policy.

## GitHub deployment handoff

The `Deploy OTL-Voice` workflow is manually triggered from `main`, validates a versioned/digest-pinned GHCR reference without printing it, and runs the tracked playbook using protected `ANSIBLE_INVENTORY` and `ANSIBLE_SSH_PRIVATE_KEY` secrets. Configure a GitHub `production` environment with required reviewers and restrict which branches/tags can run it.

The former Render deploy hook is not used. There is no untracked Render service dependency in the supported path.

## Certificates and proxy settings

- Prefer an ACME/managed certificate process with automated renewal and a reload hook.
- Keep the private key mode `0600` and owned by root; the app container never needs it.
- Set `TRUSTED_PROXY_IPS` to the exact nginx/reverse-proxy addresses. Do not trust arbitrary `X-Forwarded-For` input.
- Preserve the websocket and long-lived streaming proxy settings in `deploy/nginx/otl.conf`.
- Test HTTPS redirect, HSTS, certificate renewal, WebSocket upgrade, SSE streaming, and large request rejection after every proxy change.

## Health, readiness, and rollback

`/api/health` is a liveness endpoint. The image healthcheck runs `deploy/readycheck.py`, which checks liveness, checks Redis when required, and calls the authenticated OTL dependency endpoint when `READINESS_REQUIRE_OTL=true` (the production default). A process can therefore be alive while a required integration is unavailable; use the readiness result for traffic decisions. The readiness token is short-lived and must be renewed without printing it.

Rollback by selecting the previous immutable image digest and rerunning Ansible. Do not roll back the application while leaving a newer schema/contract in the persistent idempotency store without checking compatibility. Back up the data and idempotency volumes before a migration or destructive change.

## Post-deploy verification

```bash
curl --fail --silent --show-error https://<host>/api/health
# From the app/network context, run the configured OTL readiness probe.
```

Then verify a read-only assignment lookup, one controlled test timecard review, logout, session expiry, and an application restart. Do not test by submitting an unintended production timecard.

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

The image is a multi-stage build: a Node stage compiles the PWA, and the runtime
stage is a Python-only Debian-slim base. Node and pnpm are build-time tools
only and are deliberately absent from the runtime layer.

The Python runtime is 3.13, which is also the newest interpreter CI tests
alongside the `requires-python = ">=3.12"` floor. Read the exact base image
tags and digests from the `FROM` lines in the `Dockerfile` rather than from this
document: they are digest-pinned and Dependabot opens the bump, so a number
copied here would only ever be a stale one.

`.github/workflows/image.yml` has two jobs with different triggers and different jobs to do.

### `scan` — pre-publish gate on pull requests

Runs on any pull request that can change the image: the Dockerfile, `.dockerignore`, `backend/`, `frontend/`, `deploy/`, either lockfile, a manifest, or the workflow itself. It builds the candidate from the pull request head with `push: false` and `load: true`, then runs the same high/critical Trivy policy against the local `otl-voice:pr-candidate` tag. A finding fails the job, so the vulnerability is visible on the pull request rather than after the release exists.

`load: true` is used only here. It loads a single-platform image into the runner's daemon so the scanner can read it, and because nothing is published from this job there is no attestation to lose. It shares the `type=gha` build cache with the publish job but writes none, so a pull-request build cannot evict the publish job's cache.

This is a gate, not a proof about the shipped image: it scans the pull request build, not the release build. The two can differ if a release changes the base image outside a pull request. The `publish` job's own scan closes that gap.

### `publish` — the published artifact

Runs once per published release, or on manual dispatch with an explicit `image_tag`. It does not also fire on the tag push, because release-please creates the release and its tag in one step and a manual tag push would otherwise build, publish, and scan the same version twice. The job is:

- logs in to GHCR using the workflow token;
- builds the multi-stage image from the root lockfiles;
- publishes a semver tag, release tag, and commit-SHA tag (never `latest`);
- emits an SBOM and provenance attestations through Buildx;
- runs a high/critical Trivy image scan on the published image;
- fails the workflow on unfixed high/critical findings according to policy.

The publish scan runs against the published image, so a failing finding fails the workflow rather than preventing the push. That ordering is deliberate: the SBOM and provenance attestations that the rest of the delivery path depends on can only be produced by a push-capable Buildx output, and adding `load: true` here would drop both. The pre-publish `scan` job exists so the common case is still caught before a release, which is what makes this ordering acceptable. Treat a failed publish as unapproved and roll the digest forward; the semver tags are immutable, so the vulnerable image is never promoted to a newer version.

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

# Deployment assets

- `docker-compose.yml` is the TLS-first production stack. It forces secure cookies, requires Redis and the idempotency volume, mounts `app_data` and `idempotency_data`, and exposes nginx rather than the app port.
- `docker-compose.dev.yml` is the explicit HTTP-only local stack. It is not a production deployment.
- `nginx/otl.conf` is the TLS configuration. Port 80 redirects to HTTPS; provision `nginx/certs/fullchain.pem` and `nginx/certs/privkey.pem` outside Git.
- `ansible/playbook.yml` is the tracked host deployment target. It requires a versioned/digest-pinned GHCR image, `/opt/otl-voice/.env`, host-provisioned certificates, and a renewable readiness token, then runs a non-root/read-only container with persistent data and idempotency paths.
- `preflight.py` validates production configuration without displaying values. Run it before Ansible or Compose deployment.
- `readycheck.py` checks app liveness, Redis when required, and the authenticated OTL readiness endpoint when `READINESS_REQUIRE_OTL=true`. It is copied into the runtime image by the Dockerfile.

## Secret provisioning

Provision `/opt/otl-voice/.env` through the platform secret manager or an equivalent root-only mechanism. Set `SESSION_COOKIE_SECURE=true`, `REDIS_REQUIRED=true`, `ALLOW_IN_MEMORY_SESSIONS=false`, and explicit trusted proxy CIDRs. Do not put credentials in this directory's tracked files, an image layer, or a workflow log.

Provision a renewable, read-only session token (mode `0400`, owned by the app UID in the container) at `deploy/secrets/readiness_token` for Compose, or `/opt/otl-voice/secrets/readiness_token` for Ansible. The production healthcheck calls `/api/health/otl` with that token; it fails closed when the token or dependency is unavailable. Set `READINESS_REQUIRE_OTL=false` only for an explicitly non-production smoke stack. The token is never logged and must be rotated through the session/provisioning process.

## Image selection

Use a release tag for human inventory and prefer an immutable digest for deployment:

```bash
ansible-playbook -i deploy/ansible/inventory.example deploy/ansible/playbook.yml \
  -e 'otl_image=ghcr.io/<owner>/otl-voice@sha256:<digest>'
```

The playbook rejects `:latest` and other mutable references.

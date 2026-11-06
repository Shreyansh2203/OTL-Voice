# Production checklist — OTL-Voice

The code is production-ready (backend 688 tests, frontend 309 tests, ruff/mypy
clean, digest-pinned non-root image). What remains is operator provisioning:
values only the operator holds. This checklist turns `preflight` green and the
stack healthy. Work it top to bottom; never commit `.env`, private keys, or
`deploy/secrets/readiness_token`.

## 1. Generate the operator-owned secrets

```bash
python deploy/provision.py
# writes .env (SESSION_SECRET_KEY + ADMIN_API_KEY generated, every other
# documented variable preserved/seeded from .env.example) and
# deploy/secrets/readiness_token. Values are never printed.
```

## 2. Supply the values only the operator holds (`.env`)

| Variable | Where it comes from |
|---|---|
| `OTL_BASE_URL`, `OTL_SERVICE_USERNAME`, `OTL_SERVICE_PASSWORD` | Oracle Fusion HCM service account (https URL required) |
| `OCI_REGION`, `OCI_COMPARTMENT_ID` + one of `OCI_PRIVATE_KEY` / `OCI_PRIVATE_KEY_PATH` / `OCI_CONFIG_FILE` | OCI IAM |
| `REDIS_URL` | External Redis; **must be `rediss://`** (TLS) with a least-privilege ACL — prod compose defines no Redis service |
| `TRUSTED_PROXY_IPS` or `TRUSTED_PROXY_CIDRS` | CIDR of the reverse proxy in front of the app (compose network is `172.30.7.0/24`) |
| `CORS_ORIGINS` | Absolute https origin(s) of the PWA, e.g. `https://app.example.com` |
| Exactly one of `OIDC_ISSUER`+`OIDC_AUDIENCE`, or `AUTH_USERS` | Your IdP, or scrypt hashes generated per `.env.example` §2 |

`SESSION_COOKIE_SECURE=true`, `REDIS_REQUIRED=true`,
`ALLOW_IN_MEMORY_SESSIONS=false`, `STRICT_ASSIGNMENT=true` — leave as shipped.

## 3. TLS certificates and readiness token

```bash
mkdir -p deploy/nginx/certs deploy/secrets   # already tracked via .gitkeep
# place fullchain.pem + privkey.pem (0600) in deploy/nginx/certs/
# deploy/secrets/readiness_token is written by provision.py (0400, app UID);
# it is a renewable session token for /api/health/otl — rotate it through
# the session/provisioning process, never log it.
```

## 4. Preflight and bring-up

```bash
python deploy/preflight.py --env-file .env --mode production
# expected: "preflight: production configuration passed"
# also checks the files above (make preflight does both)
make preflight
make config          # docker compose config --quiet
make up              # docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps    # both services healthy in ~45s
```

If the app stays unhealthy, `deploy/readycheck.py` says why in container logs:
liveness, then Redis, then authenticated OTL readiness. nginx waits on
`service_healthy` by design — no traffic is served until real dependencies
answer.

## 5. Prove the integrations (before declaring ready)

```bash
RUN_LIVE_INTEGRATIONS=true LIVE_PERSON_NUMBER=<real person> \
  uv run pytest backend/tests/test_live_integrations.py
```

Mocks never prove Fusion/OCI/Redis connectivity; the 4 live tests do.

## 6. Operate

- **Backups:** `app_data` and `idempotency_data` volumes hold the idempotency
  SQLite store and app data — back them up on the same schedule as the
  database; restores need the same `IDEMPOTENCY_DB_PATH`.
- **Scaling:** single uvicorn worker is intentional (low concurrency, avoids
  per-process state surprises). Raise `--workers` only with Redis-backed
  sessions verified, which is the current design — sessions are already in
  Redis, so workers are safe to add in `Dockerfile` `CMD` if load requires.
- **Rotation:** `SESSION_SECRET_KEY`, `ADMIN_API_KEY`, Redis credentials,
  OCI keys, and the readiness token all rotate through the platform secret
  manager; changing `SESSION_SECRET_KEY` invalidates existing sessions
  (fail-closed, users log in again).
- **Frontend builds:** use `pnpm` (workspace lockfile); `npm` breaks against
  pnpm-installed `node_modules`.

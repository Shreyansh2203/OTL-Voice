# Configuration and environment variables

## Secret handling

`.env.example` is a template, not a secret. Copy it to a local ignored file or inject variables from Vault, AWS Secrets Manager, Azure Key Vault, OCI Secret Retrieval, or the platform's deployment secret store. Do not commit `.env`, `.env.*` overrides, PEM/API keys, OCI config, rendered Compose output, or CI logs containing values.

The preflight helper is intentionally non-printing:

```bash
python deploy/preflight.py --env-file .env --mode production
# or
make preflight
```

It reports variable names and validity only. A failure never prints a secret value.

## Core security

| Variable | Required | Description |
| --- | --- | --- |
| `SESSION_SECRET_KEY` | production | Random signing secret for server-side sessions. Generate at least 32 random bytes and rotate with a planned session invalidation. |
| `SESSION_TTL_SECONDS` | no | Session lifetime; default 28800 seconds (8 hours). Use a shorter value for higher-risk deployments. |
| `SESSION_COOKIE_SECURE` | production | Must be `true` behind TLS. The production Compose and Ansible paths force it. |
| `SESSION_COOKIE_SAMESITE` | no | `lax` (default), `strict`, or `none`. `none` requires secure cookies and a reviewed cross-site flow. |
| `ADMIN_API_KEY` | production | Secret for administrative catalogue endpoints. Never reuse the session or OTL password. |
| `DEV_MODE` | no | Development conveniences; must be false in production. |
| `TEST_MODE` | no | Test-only dependency bypass; must be false in production. |
| `CSP_DEV_MODE` | no | Development CSP relaxation; must be false in production. |
| `TRUSTED_PROXY_IPS` | production | Exact proxy addresses allowed to supply client IP headers. Do not use `*` unless the network boundary is documented and controlled. |
| `CORS_ORIGINS` | no | Comma-separated allowed origins. The single-origin deployment normally needs no cross-origin access. |

The browser stores the session in an HttpOnly cookie. The CSRF cookie is intentionally readable by the frontend and must be paired with the CSRF header on state-changing requests. Do not introduce localStorage bearer-token storage.

## Authentication modes

Configure exactly one production identity method. OIDC settings take precedence when `OIDC_ISSUER`/`OIDC_AUDIENCE` (or an explicit JWKS URL) are present; otherwise `AUTH_USERS` supplies per-user scrypt verifiers.

### OIDC

```dotenv
OIDC_ISSUER=https://id.example.com/realms/otl
OIDC_AUDIENCE=otl-voice-api
# Optional: use a controlled HTTPS JWKS endpoint instead of discovery.
OIDC_JWKS_URL=
OIDC_ALGORITHMS=RS256
OIDC_PERSON_NUMBER_CLAIM=person_number
OIDC_USERNAME_CLAIM=preferred_username
```

The provider-issued JWT is submitted as the login credential; the backend validates its signature, issuer, audience, expiry, and person-number claim. The issuer must use HTTPS in production. Configure the provider for MFA, lockout, and an explicit employee/person identifier claim. The application has no OIDC client secret or redirect URI because it validates bearer tokens rather than acting as a confidential authorization-code client.

### Per-user scrypt users

```dotenv
AUTH_USERS='{"10021":"scrypt$32768$8$1$SALT_BASE64URL$HASH_BASE64URL"}'
```

`AUTH_USERS` is a protected JSON object keyed by exact person number or case-insensitive username. Values may be scrypt verifier strings or objects containing `employeeId`, `username`, and `password`. The mapping must be injected through the deployment secret manager, must not contain plaintext passwords, and must not be committed or placed in a broadly readable file. Update it atomically and revoke active sessions during offboarding.

The shared `AUTH_PASSWORD`/development fallback is not an acceptable production authentication mode. `DEV_MODE` and `TEST_MODE` must never be used to make a production deployment start.

## Oracle Fusion HCM/OTL

| Variable | Purpose |
| --- | --- |
| `OTL_BASE_URL` | HTTPS HCM Time Recording endpoint, normally ending in `/hcmRestApi/resources/<version>/timeRecordEventRequests`. |
| `OTL_SERVICE_USERNAME` | Dedicated Fusion integration service account. |
| `OTL_SERVICE_PASSWORD` | Secret for that service account. |
| `FUSION_HOST_URL` | Optional tenant host override for HCM/PPM clients. |
| `FUSION_PPM_BASE_URL` | Optional PPM REST base URL. |
| `FUSION_API_VERSION` | API version when not embedded in the explicit URLs. |
| `APP_TIMEZONE` | Business timezone used for date/time mapping. See below. |
| `OTL_TIMEOUT_SECONDS` | HTTP timeout; keep bounded. |
| `DEFAULT_START_HOUR` | Default start used when a reviewed entry omits one. |
| `MAX_TIMECARD_HOURS_PER_ENTRY` | Server-side per-entry limit; default 12 hours. |
| `MAX_TIMECARD_HOURS_PER_DAY` | Server-side daily limit; default 24 hours. |
| `OTL_ALLOWED_PAYROLL_TIME_TYPES` | Comma-separated allowlist for payroll time types. |
| `OTL_ALLOWED_EXPENDITURE_TYPES` | Comma-separated allowlist for expenditure types. |
| `STRICT_ASSIGNMENT` | Keep true in production so entries must match the person's assignment. |

The Fusion service account should be able to read the required worker and assignment data and perform only the required timecard operations. Validate the exact roles and business-unit scope with the tenant administrator; Oracle role names and API privileges vary by release.

### Business timezone

`APP_TIMEZONE` takes an IANA zone name such as `Asia/Kolkata`. The application resolves it with `zoneinfo` and stamps every submitted `startTime`/`stopTime` with that zone's UTC offset, so the value reaches Fusion in the business zone's own offset rather than the server's.

If the name cannot be resolved, the application logs a warning and falls back to the host timezone. That is a deliberate availability choice, not a validation path, and it is easy to miss: a misconfigured zone produces plausible times in the wrong offset. Treat the warning as a configuration error.

Resolution needs a zone database. Linux and the pinned Debian production image ship one, so production is unaffected. A bare Windows workstation does not, which is why `tzdata` is a dev dependency scoped to `sys_platform == 'win32'`; installing the locked dev group is what makes `APP_TIMEZONE` resolve during Windows development. The frontend reads the same zone from `VITE_APP_TIMEZONE`, falling back to the browser's own zone, so set both when they must agree. `backend/tests/test_business_timezone.py` asserts the offset actually reaches the submitted timecard and that the fallback warns.

## OCI Generative AI and Speech

| Variable | Purpose |
| --- | --- |
| `OCI_REGION` | Default OCI region. |
| `OCI_GENAI_REGION` | Optional GenAI region override. |
| `OCI_SPEECH_REGION` | Optional Speech region override. |
| `OCI_COMPARTMENT_ID` | Compartment OCID for inference services. |
| `OCI_CONFIG_PROFILE` | Profile in an injected OCI config file. |
| `OCI_CONFIG_FILE` | Path to an injected OCI config file. |
| `OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT` | Inline API-key identity values. |
| `OCI_PRIVATE_KEY_PATH` | Read-only mounted private-key path. |
| `OCI_PRIVATE_KEY` | Inline key only when the platform's secret injection mechanism makes it unavoidable; prefer a file. |
| `OCI_PRIVATE_KEY_PASSPHRASE` | Key passphrase when applicable. |
| `CHAT_MODEL_ID`, `CHAT_TEMPERATURE`, `CHAT_TOP_P`, `CHAT_MAX_TOKENS` | GenAI model and generation controls. |
| `TTS_VOICE_ID`, `TTS_MODEL_NAME`, `TTS_LANGUAGE_CODE`, `TTS_SAMPLE_RATE`, `TTS_OUTPUT_FORMAT` | Speech/TTS settings. |
| `REQUEST_TIMEOUT_SECONDS` | Upstream request timeout. |

Do not place a private key in the image or repository. The OCI principal needs only the model/speech/compartment permissions required by the selected services.

## Redis and rate limiting

```dotenv
REDIS_URL=rediss://:<password>@redis.example.com:6379/0
REDIS_REQUIRED=true
```

Use a TLS Redis endpoint, a secret-managed password, network allowlists, and a separate logical database or prefix per environment. `REDIS_REQUIRED=true` makes Redis a readiness dependency and prevents a multi-instance deployment from silently falling back to process-local state. Development may use an in-memory fallback only when explicitly marked non-production.

## Idempotency and persistence

```dotenv
IDEMPOTENCY_DB_PATH=/app/data/idempotency/idempotency.sqlite3
IDEMPOTENCY_TTL_SECONDS=86400
IDEMPOTENCY_LEASE_SECONDS=120
IDEMPOTENCY_WAIT_SECONDS=35
IDEMPOTENCY_POLL_SECONDS=0.05
```

The server accepts a stable per-entry `requestId` (and the compatibility `idempotencyKey`/`Idempotency-Key` forms). The frontend creates a UUID once for a reviewed row and **keeps it for every retry of that row**, including a retry after an ambiguous failure. Reusing the key is what makes a retry safe.

Retry semantics, and how a client decides:

- **Ambiguous outcomes are not memoised.** A 5xx, or an unavailable idempotency store, releases the claim instead of completing it, so retrying with the same `requestId` makes a real second attempt. Only *definitive* rejections (4xx) are stored, so retrying one of those never rewrites Oracle.
- **`POST /api/otl/timecard` no longer returns 200 when nothing succeeded.** It answers **502** when at least one row failed in a retryable way and **422** when every row was definitively rejected, with the per-row body in both cases. 200 means at least one row was created. Status alone is not sufficient to decide anything — read each row.
- **Every row carries a `code`.** `submission_in_progress`, `request_id_conflict`, `idempotency_claim_lost`, `idempotency_unavailable` and `oracle_unavailable` are distinct and each has its own message. **Do not branch on 409 alone** — it previously meant both "retry with the same key" and "permanent conflict", and clients that read it as terminal or as retryable were both wrong.

The SQLite store is the durable deduplication record; the in-process fallback is only a degraded single-process mode and is not a substitute for the volume. If the store cannot be opened the write is refused (503) rather than silently degraded, because degrading would lose every deduplication guarantee.

Two independent windows govern a submission. `IDEMPOTENCY_TTL_SECONDS` is how long a completed result stays replayable. `IDEMPOTENCY_LEASE_SECONDS` is the crash-recovery window for a claim that has started but has not finished: while the lease is live, any other submission of the same `requestId` is refused and waits for the first result, so a live write is never duplicated. When the lease expires the claim is treated as abandoned and the next attempt reclaims it, so a process crash, a container restart, or a lost write cannot block a `requestId` for the whole TTL. The lease is clamped to at most the TTL, so it can never outlive the record it protects.

Set the lease above the longest expected single-entry write. The default 120s is comfortably above the default 30s `OTL_TIMEOUT_SECONDS` bound on one write. Because an expired lease is reclaimable, a write that reached Oracle but died before the result was stored can be duplicated by the retrying client; that is the deliberate cost of bounding the outage, and the alternative is a `requestId` that stays permanently unusable.

Keep the idempotency volume until the configured TTL plus the maximum retry/window has elapsed. Back it up with the application data and restrict its mode/ownership. Do not copy a live SQLite file without coordinating a consistent snapshot.

## Health and readiness

| Variable | Purpose |
| --- | --- |
| `READINESS_BASE_URL` | Internal app origin used by the bundled probe; normally `http://127.0.0.1:8000` inside the app container. |
| `READINESS_URL` | Liveness URL, normally `/api/health`. |
| `READINESS_REQUIRE_OTL` | `true` in production to fail readiness when the authenticated OTL dependency probe cannot run. |
| `READINESS_OTL_URL` | Authenticated OTL readiness URL, normally `/api/health/otl`. |
| `READINESS_AUTH_TOKEN_FILE` | Read-only file containing a renewable, short-lived session token for that probe. |
| `READINESS_INSECURE_TLS` | Development-only escape hatch; never set in production. |

## PWA/mobile

`VITE_API_URL` is required by the guarded Capacitor mobile build and must be an HTTPS origin. Local web development uses Vite's same-origin `/api` proxy; do not bake a localhost URL into a production mobile bundle.

## Observability

`SENTRY_DSN` is optional. If enabled, use a project-specific DSN, scrub employee identifiers and prompts, and set sampling appropriate for the organization's retention policy. Never send session cookies, OCI keys, Fusion passwords, or raw audio to an error tracker.

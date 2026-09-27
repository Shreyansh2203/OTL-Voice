# Security model

## Security objectives

- A person can act only on their own authenticated session and authorized Fusion assignments.
- A session cookie is not readable by browser JavaScript and is protected by TLS in production.
- A model response cannot create a timecard without the user's explicit review/approval.
- A retry cannot silently create a second Oracle record when the request ID and durable idempotency store are preserved.
- A compromised frontend or a leaked static asset does not reveal server credentials.
- Operators can detect, contain, and rotate credentials without relying on source-code changes.

## Controls in this repository

### Transport and proxy

- Production nginx serves TLS 1.2/1.3 and redirects port 80 to HTTPS.
- `SESSION_COOKIE_SECURE=true` is enforced by the production Compose and Ansible configurations.
- HSTS, frame denial, content-type protection, referrer policy, CSP, and body-size limits are applied at the proxy/application layers.
- WebSocket and SSE routes have bounded/no-buffer proxy behavior. Do not replace the proxy config with a generic static file server.

### Application

- Session JWTs are signed and expire; logout/expiry can be revoked, with Redis required for distributed revocation.
- State-changing browser requests use a CSRF cookie/header pair.
- The session cookie is HttpOnly. Do not add localStorage bearer-token support.
- Auth modes are explicit: OIDC or per-user scrypt. Shared development passwords are not a production control.
- Request body size, rate limits, and OIDC/Fusion validation limit resource abuse.
- The timecard layer validates assignment, hours, dates, payroll/expenditure allowlists, and stable request IDs before a write.

### Container and supply chain

- Multi-stage builds keep Node tooling and source artifacts out of the runtime image.
- Base images are versioned and digest-pinned where practical; the pnpm and uv tool versions are pinned.
- CI uses `uv sync --locked` and `pnpm install --frozen-lockfile`.
- Every third-party GitHub Action is pinned to a full 40-character commit SHA with the release tag kept as a trailing comment, so a mutable tag move cannot change what a workflow executes. Dependabot's `github-actions` ecosystem in `.github/dependabot.yml` opens the weekly bump that updates those pins; reviewing that pull request is the point at which a new action version is approved.
- The runtime runs as UID 10001, drops capabilities, uses a read-only root filesystem, and has bounded temporary storage.
- GHCR publication emits SBOM/provenance and runs a high/critical image scan.
- CodeQL and Dependabot remain enabled.

### Dependency vulnerability scanning

Known-vulnerable dependencies fail the build rather than being reported and ignored. Two blocking jobs run in `.github/workflows/ci.yml`:

| Job | Trigger | What it enforces | How it fails |
| --- | --- | --- | --- |
| `Dependency Audit` | every push and pull request, plus the weekly `schedule` | `pip-audit` over the exact set exported from `uv.lock`, and `pnpm audit --audit-level=high` over the workspace lockfile | `pip-audit` exits non-zero on any advisory, and `--strict` also makes a dependency-collection failure fatal so a broken export cannot pass silently. `pnpm audit` exits non-zero at or above the configured level. |
| `Dependency Review` | pull requests only | `actions/dependency-review-action` over the pull request's dependency diff, at `fail-on-severity: moderate` | The action fails the job when the diff introduces a finding at or above that severity. |

`pip-audit` is a dev dependency in `pyproject.toml`, so the audit runs against the same locked environment the tests use and the version is reproducible. It queries the PyPI advisory service, so the job needs network access; a run that cannot reach the advisory database is a failure to investigate, not a clean bill of health.

The `schedule` trigger makes the whole-tree audit run weekly, which is what catches a newly published advisory against an unchanged lockfile. Fix an advisory in the manifest and update the lockfile in the same change, or document why an accepted risk is not exploitable here; do not suppress a finding to make the job green.

## Secrets and sensitive data

Never commit or log:

- `.env` files or rendered environment dumps;
- OCI private keys, API key fingerprints paired with keys, or `~/.oci/config`;
- Fusion/OTL passwords, OIDC signing/JWKS credentials, admin keys, readiness session tokens, or session cookies;
- raw prompts, transcripts, audio, employee exports, or database files containing personal data.

The preflight helper only reports names/status. Configure the host, CI, and secret manager so command output is not captured alongside values. Restrict backups of the app data/idempotency volumes and define retention/deletion requirements with privacy and payroll owners.

## Data flow and privacy

The browser sends text and, when requested, microphone audio to the backend. The backend sends the minimum required context to OCI for generation/speech and the minimum required fields to Fusion for an approved timecard. Model output is advisory until the user confirms the structured review. External providers' retention and training settings must be reviewed before production use.

Browser speech recognition may be used as a fallback. If that fallback is enabled, disclose the alternative processor and obtain the required organizational/employee consent.

## Abuse cases and responses

| Abuse | Preventive control | Detection/response |
| --- | --- | --- |
| Credential stuffing | OIDC MFA/lockout or scrypt verifier plus rate limits | Auth rate-limit alerts, provider lockout reports, revoke sessions |
| CSRF/timecard write | CSRF pair, SameSite cookie, explicit review | Reject anomalous writes, inspect idempotency records and Oracle audit |
| Replay/duplicate write | Stable request ID + persistent SQLite idempotency | Compare request/Oracle IDs, preserve store during incident |
| Service-account abuse | Least privilege, secret manager, network restrictions | Rotate immediately, review Fusion audit logs |
| SSRF/proxy header abuse | Fixed upstream, trusted proxy list, no arbitrary forwarded headers | Review proxy/app logs, rotate app secret if exposure suspected |
| Dependency outage | Explicit readiness and bounded timeouts | Keep liveness separate, degrade safely, do not claim success |

## Security review checklist

Before a production release, verify:

- `docker compose config` and `docker build --check` pass.
- No `:latest` image is selected; a digest is recorded in the deployment inventory.
- TLS, HSTS, secure cookies, trusted proxies, and certificate renewal are tested.
- OIDC/scrypt mode and offboarding are tested.
- Redis is required and reachable for the intended replica count.
- Idempotency and data volumes are persistent, backed up, and access-controlled.
- SBOM, image scan, CodeQL, Dependabot, and dependency update results are reviewed.
- Logs/artifacts contain no secrets or unnecessary employee/chat data.
- A rollback and credential-rotation drill has been completed.

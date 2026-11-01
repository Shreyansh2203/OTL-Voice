# Authentication and session security

## Supported production modes

OTL-Voice has two deliberate production authentication paths. Configure OIDC or the per-user scrypt mapping; do not run a shared fallback password in production.

### OIDC (recommended for enterprise SSO)

1. Register an API/resource audience for the OIDC identity provider and issue JWTs with the stable person-number claim.
2. Configure `OIDC_ISSUER` and `OIDC_AUDIENCE` together, or configure an explicit HTTPS `OIDC_JWKS_URL`; use discovery when only the issuer is set.
3. Require MFA, lockout, and lifecycle controls in the provider.
4. Map the configured person-number and username claims to the employee/person identifier used by Fusion. Reject missing, inactive, or ambiguous identities.
5. Test logout, IdP session expiry, clock skew, claim changes, key rotation, and account deactivation.

The browser submits the provider-issued OIDC JWT as the login credential. The backend validates its signature, issuer, audience, expiry, and claim mapping, then creates a short-lived server session. The application does not store an OIDC client secret because it is a resource server, not a confidential authorization-code client. The resulting session JWT is not placed in localStorage.

### Per-user scrypt users

For a small isolated deployment without an IdP, provision one record per person in the `AUTH_USERS` JSON mapping. Each value must use a unique random salt and a memory-hard scrypt verifier with a reviewed cost policy. Inject the mapping as a secret with mode `0600` or stricter and restrict it to the app UID.

Operational rules:

- Never store plaintext passwords or reuse a person's OCI/Fusion password.
- Create and rotate records through an atomic provisioning process.
- Remove a record immediately on termination; revoke existing sessions as part of offboarding.
- Protect backups of the users mapping as sensitive authentication data.
- Do not put the mapping in Git, an image layer, a CI artifact, or a broadly readable host directory.
- Test lockout/rate-limit behavior and verify that a user cannot select a different person's identifier after authentication.

## Session and cookie model

- The session cookie is `HttpOnly`, `Secure` in production, scoped to `/`, and sent with same-origin requests.
- The session lifetime is controlled by `SESSION_TTL_SECONDS` and should be no longer than the business risk requires.
- A readable CSRF cookie/header pair protects state-changing browser requests. Do not disable CSRF by putting a bearer token in a URL or localStorage.
- Session cookies are invalidated on logout/expiry. Redis-backed revocation is required when more than one process is deployed.
- The frontend must use credentialed requests and must not log response cookies or authorization headers.
- `SESSION_COOKIE_SAMESITE=none` is not a default. It requires `Secure`, an explicit cross-site architecture, and a review of CSRF/CORS behavior.

## Threat model

| Threat | Control |
| --- | --- |
| Stolen browser session cookie | HttpOnly cookie, Secure transport, short TTL, rotation, revocation, TLS-only access. |
| Cross-site state-changing request | CSRF cookie/header validation, SameSite policy, origin checks, no token in URLs. |
| User impersonation by changing person number | OIDC claim binding or per-user scrypt record binding; server-side assignment checks. |
| Service-account compromise | Least-privilege Fusion account, secret manager, rotation, network restrictions, no browser exposure. |
| Dependency outage or Redis failure | `REDIS_REQUIRED=true` and readiness failure for distributed production; explicit degraded development mode. |
| Secret leakage in logs | Preflight reports names only, structured redaction, no `no_log`-less credential commands, short retention. |

## Preflight and rotation

Run `make preflight` before deployment. It rejects placeholder values, insecure cookies, missing auth settings, and missing production dependencies without displaying values.

When rotating a secret:

1. Provision the replacement in the secret manager.
2. Deploy a new version and verify health/readiness.
3. Verify one canary login and an Oracle read-only operation.
4. Revoke the old Fusion/OCI/OIDC credential.
5. For session-secret rotation, choose a controlled invalidation window and ask users to sign in again; do not log old or new values.
6. Preserve the idempotency volume while pending timecard retries are completed.

See [operations.md](operations.md) for the incident checklist.

## Development and test exceptions

`DEV_MODE` and `TEST_MODE` permit temporary development behavior and are used by credential-free tests. They must be false in production, and CI must not run live integration tests by default. A successful mocked login is not evidence that OIDC, scrypt, Oracle, or OCI credentials are correct.

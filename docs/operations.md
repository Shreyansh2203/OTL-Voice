# Operations, incidents, and secret rotation

## Routine operations

- Check liveness, readiness, container health, nginx errors, and certificate expiry.
- Review Fusion and OCI audit logs for unexpected reads/writes.
- Confirm the idempotency and catalogue volumes are mounted and writable by UID 10001.
- Monitor Redis connectivity, rate-limit behavior, session revocation, and upstream timeouts.
- Keep a deployment record containing the image digest, configuration revision, certificate expiry, and rollback digest. Never record secret values.

## Incident severity

### Sev 1: suspected credential or payroll-data exposure

1. Declare an incident, preserve evidence, and stop further writes if duplicate or unauthorized activity is possible.
2. Revoke/rotate the affected Fusion service account, OCI key, OIDC verifier/JWKS configuration, admin key, or session secret in that order of blast radius.
3. Preserve the idempotency and application volumes; do not delete them while retries or forensic comparisons are in flight.
4. Query Fusion/OCI audit logs and application logs using redacted identifiers. Do not paste raw logs into a public issue.
5. Deploy a known-good image digest and verify assignment/read-only paths before re-enabling writes.
6. Notify privacy/payroll/security owners, document timeline and impact, and complete a post-incident review.

### Sev 2: dependency or deployment failure

1. Check `/api/health` separately from the configured readiness/dependency probe.
2. Inspect container, nginx, Redis, OCI, and Fusion timeout/error summaries.
3. Roll back to the last known-good digest if the new image is implicated.
4. If the idempotency store is unavailable, pause timecard writes rather than bypassing deduplication.
5. Recover the dependency, run the opt-in live read-only checks, then resume a controlled write test.

## Credential rotation runbook

### Fusion service account

1. Create a replacement least-privilege account and validate it in a non-production window.
2. Update the secret manager and restart/recreate the app with the new environment.
3. Verify a read-only worker/assignment lookup and a controlled test timecard flow.
4. Revoke the old account and review its audit history.

### OCI API key

1. Create a new key/fingerprint with only the required policies and confirm model/speech access.
2. Update the mounted credential or secret value, restart the workload, and test a short generation/speech request.
3. Revoke the old key. Check for use from unexpected networks or principals.

### OIDC verifier or JWKS configuration

1. Rotate the IdP signing key or update the controlled `OIDC_JWKS_URL`/issuer configuration using the provider's overlap procedure.
2. Update the app secret/configuration, verify a fresh OIDC login, and then retire the old signing key.

### Session/admin secret

1. Schedule a short invalidation window.
2. Rotate the value, deploy, verify new logins, and invalidate old sessions.
3. Check logs and artifacts for accidental disclosure. Never echo either value during verification.

### TLS certificate

1. Issue the new certificate before expiry, validate the full chain and hostname, and install it with mode `0600`.
2. Run `nginx -t`, reload/restart nginx, and verify HTTPS/WebSocket/SSE from an external network.
3. Remove the old private key only after rollback requirements and retention policy permit it.

## Backup and restore

Back up the catalogue/data and idempotency volumes using the platform's encrypted snapshot mechanism. Test restore regularly. A restore must keep the app image, schema, and idempotency records from the same compatible release whenever possible. For SQLite, use a consistent snapshot rather than copying a live file from an arbitrary instant.

## Communication

Incident reports should include the image digest, affected time window, service/tenant, user impact, and remediation. Exclude passwords, private keys, cookies, bearer tokens, raw prompts/audio, and unnecessary employee identifiers. Preserve original logs in the approved restricted system rather than attaching them to a public issue or pull request.

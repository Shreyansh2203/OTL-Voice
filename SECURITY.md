# Security Policy

This document is the entry point for reporting a security problem in OTL-Voice,
and the summary of what the project does and does not protect. The threat model
and the per-control reasoning live in [docs/security.md](docs/security.md);
operational response and rotation procedures live in
[docs/operations.md](docs/operations.md).

## Reporting a vulnerability

**Do not open a public issue, pull request, or discussion for a security
problem.** Public reports are visible immediately and cannot be retracted.

Report it privately through GitHub's **Security → Report a vulnerability**
("Report a vulnerability" / "New draft security advisory") on the repository, at
<https://github.com/Shreyansh2203/OTL-Voice/security/advisories/new>. That
channel requires a GitHub account and alerts the maintainers privately.

If the advisory route is unavailable or you are not able to create an account,
open a GitHub issue that says only "security report — please open a private
channel", with **no technical detail**, and the maintainers will arrange a
channel.

Please include, as far as you are able:

- the affected component (backend, frontend/PWA, deployment manifests, CI);
- what an attacker can achieve, and what access they need to start;
- reproduction steps, request/response samples with real employee data removed;
- whether any real Oracle timecard, employee number, or transcript was exposed.

### What to expect

| Stage | Target |
| --- | --- |
| Acknowledgement that a human has read the report | 3 business days |
| Assessment, severity, and whether it is accepted | 10 business days |
| Fix released for accepted reports | As fast as the severity allows; criticals are prioritised ahead of planned work |

The maintainer is a single person working on this in their own time. A missed
target is a reason to say so on the board or in the advisory thread, not a reason
to assume the report was dismissed.

### What is *not* a vulnerability in this project

Reporting these is welcome, but they will be closed as out of scope:

- **You can only submit timecards for yourself.** Employee number and employee
  name are taken from the authenticated session, never from the request body.
  A user cannot write another person's timecard.
- **The frontend is a client.** Anything enforced only by the PWA — the review
  and approve step, client-side field validation, `localStorage` clearing — is a
  usability control, not a security boundary. Bypassing the UI does not grant
  access to any other employee or project than the session already allows.
- **Rate-limit thresholds.** The exact numbers in
  [docs/configuration.md](docs/configuration.md) are operator-tunable. Reporting
  the current value is not a finding; an unbounded bypass is.
- **Findings that require an already-compromised host**, an attacker who can
  read the server's environment, or the Oracle/OCI credentials themselves.
- **Automated dependency scanner output** that is already tracked by
  Dependabot/CodeQL with no demonstrated impact in this application. Include the
  impact if you want it reprioritised.

### Disclosure

Fixes ship as a normal release through the existing GHCR/release-please flow,
with a `fix:` commit and a CVE/GHSA identifier in the advisory when one is
assigned. Please do not publish details of an unfixed problem, including in
social posts, until the advisory is published.

## Supported versions

Security fixes land on `main` and are released by release-please. There is no
long-term-support branch.

| Version | Supported |
| --- | --- |
| Latest release from `main` | Yes |
| Previous release | Security fixes only, until the next release ships |
| Any build from a fork or from a `main` commit older than the latest release | No |
| Any release still pinned to an image tag Dependabot has since superseded | No — upgrade first |

There is no declared minimum supported version. If you are running something
older than the previous release, upgrade before reporting anything: the report
will otherwise be triaged against code that is no longer shipped.

## Security model in one page

- **Authentication.** Production runs either OIDC or an `AUTH_USERS` mapping of
  exact person numbers to unique scrypt verifiers. `DEV_MODE` and `TEST_MODE`
  are development conveniences that weaken these controls and must never be set
  in production; `deploy/preflight.py` fails closed if the production
  configuration is incomplete.
- **Sessions.** HS256-signed, HttpOnly, Secure, `SameSite`, `__Host-`-prefixed
  cookies. Resolving a session also requires a server-side record, so a valid
  signature alone is not enough. Bearer tokens are not accepted on
  state-changing methods.
- **CSRF.** A session-bound double-submit token is required on every
  state-changing request. The client refreshes once on an expired session or a
  rotated CSRF token instead of surfacing the failure.
- **Secrets.** Injected at runtime only. `.env`, PEM files, OCI config, rendered
  Compose files with credentials, and browser exports must never be committed.
  `pnpm --dir frontend run verify` and the backend suites contain assertions
  aimed at exactly these leaks; do not weaken them to make a change pass.
- **Data minimisation.** The PWA persists only the current conversation and
  draft per employee, under a versioned key, and clears it on session loss. No
  bearer token, cookie value, or Oracle credential is ever placed in
  `localStorage`, a query string, a screenshot, or a log.
- **Error contract.** API errors return a fixed, sanitised message plus a
  correlation ID. Tracebacks, SQL, file paths, environment variable names, and
  credential material must not cross the wire. A regression here is a security
  bug, not a polish item.
- **Fail-closed dependencies.** Rate limiting and the session store refuse to
  fall back to in-process behaviour when Redis is unavailable in production.
- **Content Security Policy**, frame denial, `nosniff`, body-size limits, and
  rate limits are set in the application, not only at the proxy.
- **Supply chain.** Lockfiles are committed and checked, dependencies are pinned
  and hashed, images are scanned with SBOM and provenance attached, and
  Dependabot, CodeQL, and release-please are part of the supported delivery
  path.

## Hardening and disclosure expectations for contributors

- Never weaken or delete a security test, never add a `skip`/`xfail` around one,
  and never widen an `allowlist` in an error sanitiser, a Sentry scrubber, or a
  CSP to get a green run.
- Never log a secret. Logging a variable *name* is fine; logging its value is
  not, even in a development build.
- A new endpoint needs an explicit authentication decision recorded in
  [docs/security.md](docs/security.md), including what an unauthenticated caller
  observes.
- A new persisted key in the PWA needs a documented owner, a version, and a
  clear-on-logout story.
- Treat a new outbound integration (Oracle, OCI, a model provider, Sentry) as
  untrusted until proven otherwise: check what leaves the boundary, and scrub it.

## Verification

The repository's own gates are the first thing to run on a security-sensitive
change:

```bash
make verify
make coverage
make test-e2e-matrix
pnpm --dir frontend exec vitest run --coverage
```

The gates live in the root `pyproject.toml` (`fail_under`) and
`frontend/vite.config.ts` (`test.coverage.thresholds`); each coverage run prints
the measured percentages. Neither number is restated in prose anywhere in this
repository, and neither is duplicated in the CI workflow or the Makefile, so
there is no second copy to drift. Read them from the config files.

# Contributing

Thanks for working on OTL-Voice. This repository is a reference implementation, so the bar is "a reviewer can verify it" rather than "it works on my machine".

## Before you start

- Read [README.md](README.md) for the architecture and the security posture, and [docs/README.md](docs/README.md) for the topic map.
- Use a least-privilege identity. Never commit a `.env`, a key, a session cookie, or raw employee or chat data — not in code, comments, tests, fixtures, artifacts, or logs.
- Development-mode conveniences (`DEV_MODE`, `TEST_MODE`, `ALLOW_IN_MEMORY_SESSIONS`) exist for a workstation. They are not a deployment configuration and must never be set in production.

## Setup

```bash
uv sync --locked --all-groups
pnpm install --frozen-lockfile
```

Run pnpm from the repository root. The root `pnpm-lock.yaml` is the only workspace lockfile; a nested `frontend/pnpm-lock.yaml` must never be created or committed.

The dev dependency group carries `tzdata` on Windows because `zoneinfo` needs a zone database that a bare Windows install does not ship. Without it an IANA `APP_TIMEZONE` resolves to nothing and the application falls back to the host timezone.

## Commit and pull request conventions

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <imperative summary>

<optional body: why, not what>
<optional footer: issue or breaking-change references>
```

- Allowed types include `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`, and `revert`.
- Keep the summary in the imperative mood and under 72 characters; do not end it with a period.
- Mark a breaking change with `!` after the type/scope and a `BREAKING CHANGE:` footer.
- One logical change per commit. A refactor and a behaviour change do not belong in the same commit.
- Release automation derives the changelog from these messages, so a vague `fix: stuff` summary is a real cost.

Scope to what is useful and stable: `fix(chat): ...`, `ci(cd): ...`, `docs(configuration): ...`.

A pull request should:

1. Explain the problem and the approach, and say what is deliberately out of scope.
2. Include tests for behaviour changes and update the documentation that a reviewer would otherwise get wrong.
3. Update `pyproject.toml`/`pnpm-lock.yaml` or `package.json`/`pnpm-lock.yaml` in the same change as the manifest, never separately.
4. State explicitly if any gate could not be run locally and why.

## Quality gates

Run everything before you push:

```bash
make verify     # format-check + lint + typecheck + unit tests
make coverage   # both coverage gates
make lock-check # lockfiles match the manifests
```

Individually:

| Gate | Command |
| --- | --- |
| Python lint | `uv run ruff check .` |
| Python format | `uv run ruff format --check backend deploy` |
| Python types | `uv run mypy backend` |
| Python tests | `uv run pytest backend/tests` |
| Backend coverage | `uv run pytest backend/tests --cov=backend --cov-fail-under=80` |
| Frontend types | `pnpm --dir frontend exec tsc -b tsconfig.app.json tsconfig.node.json` and `--project tsconfig.tests.json` |
| Frontend lint | `pnpm --dir frontend run lint` |
| Frontend format | `pnpm --dir frontend exec prettier --check "src/**/*.{ts,tsx}"` |
| Frontend tests | `pnpm --dir frontend run test:unit` |
| Frontend coverage | statements 83, lines 86, functions 84, branches 76 |
| Frontend build | `pnpm --dir frontend run build` |
| Dependency audit | `uv run pip-audit` over the exported lock, and `pnpm audit --audit-level=high` |
| Compose config | `make config` and `make config-dev` |

The coverage floors are real gates. Raise them only with tests that prove the new behaviour, and never reach a number by excluding a file, adding a coverage pragma, deleting a test, or marking one skipped. A test that asserts nothing is worse than no test.

`make` is a convenience wrapper, not a dependency. Every target maps to a command you can run directly.

## Tests without live credentials

The default suite is fully offline. It mocks Oracle, OCI, and Redis, and the live integration tests are opt-in and skip themselves. On a fresh checkout:

```bash
make smoke
uv run pytest backend/tests
pnpm --dir frontend run test:unit
pnpm --dir frontend run build
```

End-to-end tests need the Playwright browsers once:

```bash
pnpm --dir frontend exec playwright install --with-deps chromium firefox webkit
make test-e2e-chromium   # fast local loop
make test-e2e-matrix     # the full matrix, as CI runs it
```

Visual snapshots are platform-specific. Update one only after reviewing the rendered diff and the accessibility impact, and update the platform the CI runner uses.

## Tests with live credentials

Only for work that genuinely needs a real tenant, and only with a dedicated least-privilege test identity against an isolated tenant:

```bash
RUN_LIVE_INTEGRATIONS=true \
LIVE_PERSON_NUMBER=<test-person> \
make test-live
```

That test can call Oracle worker lookup, OCI GenAI, OCI TTS, and Redis, and it will consume quota. Read [backend/tests/test_live_integrations.py](backend/tests/test_live_integrations.py) before running it, confirm the target tenant, and capture only redacted output. Never add live secrets to CI configuration or pull-request secrets, and never raise the live gate from non-interactive CI.

## Security controls you must not weaken

Reviewers reject changes that relax any of these, even in a test:

- CSRF token handling, the CSP (including `CSP_DEV_MODE` staying off in production), and the Sentry scrubbing rules;
- rate limiting, the request body-size limit, and the SPA path-traversal guard;
- `HttpOnly`, `Secure`, `SameSite` cookies, and the opt-in gating of the live test suite;
- the read-only, non-root container posture.

Do not add bearer-token authentication. Do not add an `except: pass` or a swallowed exception to make a gate pass. If a control seems wrong, open an issue describing the threat before changing it.

## Images and dependencies

- Every GitHub Action is pinned to a full 40-character commit SHA with the release tag as a trailing comment. Dependabot's `github-actions` ecosystem opens the bump; reviewing that pull request is how a new action version is approved.
- The image is built from the pinned Debian base and the root lockfiles. Keep the runtime free of Node tooling and source artifacts.
- A dependency with a known advisory is fixed in the manifest and the lockfile in the same change, or documented with a reason it is not exploitable here. Do not suppress a `pip-audit` or `pnpm audit` finding to go green.

## Documentation

`docs/` is part of the deliverable. If a change makes a description wrong, fix the description in the same change. Keep every relative link and table-of-contents anchor resolvable, and prefer stating the trade-off over implying one.

## License

Copyright (c) 2026 Shreyansh Srivastava. See [LICENSE](LICENSE).

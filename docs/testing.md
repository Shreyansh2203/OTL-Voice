# Testing and CI

## Test layers

1. **Backend unit/API tests** mock Oracle, OCI, Redis, and time dependencies. They run without credentials and are the default CI gate.
2. **Frontend unit tests** use Vitest and Testing Library. They run without a browser or backend.
3. **Playwright browser tests** run the full Chromium, Firefox, and WebKit project matrix with mocked external API boundaries. They verify UI behavior, accessibility, voice state transitions, and visual baselines.
4. **Container smoke tests** build the non-root image and wait for `/api/health` in `TEST_MODE` with throwaway values.
5. **Live integration tests** are opt-in and may read or write Oracle data. They are not part of ordinary CI.

## Locked setup

```bash
uv lock --check
uv sync --locked --all-groups
pnpm install --frozen-lockfile
```

The root workspace lockfile is canonical. Do not use `uv lock` or an unlocked pnpm install in CI to silently repair drift. A maintainer who changes a manifest must update the appropriate lockfile in the same change and run the frozen checks.

## Backend

```bash
uv run ruff check .
uv run ruff format --check backend deploy
uv run mypy backend
uv run pytest backend/tests --cov=backend --cov-report=term-missing --cov-report=xml
```

Note the absence of `--cov-fail-under` on that last line. The backend gate is
`fail_under` in `[tool.coverage.report]` in the root `pyproject.toml`, and
pytest-cov reads it from there. The CI workflow and the `make coverage` target
both invoke the identical command with no override flag, so local and CI apply
the same number and there is exactly one place to change it.

The CI workflow uploads `coverage.xml` and `.coverage` even when a test step fails. The 80% gate matches what the suite genuinely measures today — **82.5%** as last measured on the 1.0.0 baseline, against 419 passing and 4 skipped tests — rather than sitting far below it, so a regression is caught and improving coverage is rewarded. The headroom above the gate is roughly 2.5 points, which is deliberately thin: it is enough to absorb a small amount of platform drift, not enough to hide a deleted test. Raise it as tests land, and never reach the number by excluding code or adding a coverage pragma.

### Supported Python range

`pyproject.toml` declares `requires-python = ">=3.12"`, and the CI `backend` job
runs as a matrix over `['3.12', '3.13']` so the declared floor is tested on
every push rather than assumed. The container image ships 3.13, and 3.12 is the
oldest interpreter the project claims to support.

To reproduce the 3.13 leg locally without disturbing the project venv, point
`uv` at a separate environment:

```bash
UV_PROJECT_ENVIRONMENT=.venv313 uv run --python 3.13 pytest backend/tests
```

Pointing `uv` at a separate environment is deliberate. Plain
`uv run --python 3.13 ...` reinterprets the existing `.venv` as a 3.13
environment in place, which destroys the working 3.12 environment — and on a
checkout where another process holds a file lock, the removal fails halfway and
leaves a broken `.venv` rather than either interpreter. `.venv*/` is ignored by
git so the scratch environment does not show up in `git status`.

Both legs pass on the 1.0.0 baseline: 419 passed, 4 skipped on CPython 3.12.14
and on CPython 3.13.15. A change that passes on one and fails on the other is a
compatibility regression, not a flake. The skipped tests are the opt-in live
integration tests described below.

## Frontend

```bash
pnpm --dir frontend run typecheck
pnpm --dir frontend run lint
pnpm --dir frontend run build
pnpm --dir frontend exec vitest run --coverage
```

The enforced thresholds live in `frontend/vite.config.ts` under `test.coverage.thresholds` and are deliberately not repeated here or in `README.md`, `CONTRIBUTING.md`, or `SECURITY.md`. Restating a config value in prose is how those documents came to disagree with the code in the first place; read the thresholds from the config, and the measured percentages from the coverage table the run prints. `make coverage` runs both ecosystems and applies both gates.

`frontend/vite.config.ts` is the CI gate too, and that is on purpose. A
`--coverage.thresholds.*` command-line flag takes precedence over the config
file, so the CI job used to carry a second, hand-maintained copy of all four
numbers. Those flags have been removed: CI and local runs now read the same
config, and there is nothing left to drift. Do not reintroduce a CLI override.

Branches are held to a lower floor than statements because branch coverage counts defensive guards, optional-chaining chains, and prop defaults that are not worth a test each.

CI performs an additional strict TypeScript invocation over `frontend/src` and `frontend/tests`, so a test-only type error cannot be hidden by the application tsconfig exclusions. The frontend job uploads JSON/HTML coverage and the built PWA.

## Dependency auditing

```bash
uv export --all-groups --no-emit-project --no-hashes --format requirements-txt -o requirements.txt
uv run pip-audit --strict --requirement requirements.txt
pnpm audit --audit-level=high
```

These are the same commands the `Dependency Audit` CI job runs, and they are part of the blocking gate on every push, pull request, and the weekly `schedule` run. `pip-audit` is pinned in the dev dependency group so the auditor version is reproducible. See [security.md](security.md) for the policy.

## Playwright

Install the browsers once:

```bash
pnpm --dir frontend exec playwright install --with-deps chromium firefox webkit
```

Run the complete matrix:

```bash
make test-e2e-matrix
# equivalent:
pnpm --dir frontend exec playwright test \
  --project=chromium --project=firefox --project=webkit
```

The CI job starts FastAPI and Vite with test-mode environment variables, runs every Playwright test, and uploads reports, traces, and backend/Vite logs on success or failure. Visual snapshots are platform-specific; update them only after reviewing the rendered diff and accessibility impact.

For a quick local loop:

```bash
make test-e2e-chromium
```

## Credential-free smoke checks

These are safe on a fresh checkout:

```bash
make smoke
uv run pytest backend/tests
pnpm --dir frontend run test:unit
pnpm --dir frontend run build
make image-check
make config-dev
```

The optional Compose production configuration check can run without a local `.env`; `make up` still runs the non-printing production preflight and refuses to start without a valid secret file. Configuration checks do not contact Oracle/OCI and do not print values.

## Opt-in live integration test

Use a dedicated, least-privilege test identity and an isolated tenant:

```bash
RUN_LIVE_INTEGRATIONS=true \
LIVE_PERSON_NUMBER=<test-person> \
uv run pytest backend/tests/test_live_integrations.py
```

The test may call Oracle worker lookup, OCI GenAI, OCI TTS, and Redis. Read the test file before running, confirm the target tenant, and capture only redacted results. Never add live secrets to CI configuration or pull-request secrets.

## Failure triage

- Check the uploaded coverage/Playwright artifact before rerunning locally.
- For an E2E startup failure, inspect `/tmp/otl-backend.log` and `/tmp/otl-vite.log` from the artifact; do not print environment files.
- For a visual failure, compare the platform-specific baseline and check fonts, viewport, animations, and reduced-motion settings.
- For a dependency failure, use the opt-in live test only after checking tenant/network policy and quota.
- For lockfile drift, fix the manifest/lockfile in a dedicated change; never bypass frozen installation in CI.

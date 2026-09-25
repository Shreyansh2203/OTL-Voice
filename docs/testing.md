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
uv run ruff format --check backend
uv run mypy backend
uv run pytest backend/tests --cov=backend --cov-report=term-missing --cov-fail-under=65
```

The CI workflow uploads `coverage.xml` and `.coverage` even when a test step fails. The 65% gate is a minimum regression floor; critical modules should be raised as they receive focused tests.

## Frontend

```bash
pnpm --dir frontend run typecheck
pnpm --dir frontend run lint
pnpm --dir frontend run build
pnpm --dir frontend exec vitest run --coverage \
  --coverage.thresholds.statements=75 \
  --coverage.thresholds.lines=75 \
  --coverage.thresholds.functions=75 \
  --coverage.thresholds.branches=70
```

CI performs an additional strict TypeScript invocation over `frontend/src` and `frontend/tests`, so a test-only type error cannot be hidden by the application tsconfig exclusions. The frontend job uploads JSON/HTML coverage and the built PWA.

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

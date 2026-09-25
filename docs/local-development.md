# Local development

## Supported workstation setup

| Workstation | Python | Node/pnpm | Container option |
| --- | --- | --- | --- |
| Windows 10/11 | Python 3.12+ | Node 22, pnpm 12.6.0 | Docker Desktop + Compose v2.24+ |
| Ubuntu/Debian | Python 3.12+ | Node 22, pnpm 12.6.0 | Docker Engine + Compose v2.24+ |
| macOS | Python 3.12+ | Node 22, pnpm 12.6.0 | Docker Desktop + Compose v2.24+ |

Install `uv` using its official platform installer or package manager. Enable Corepack or install pnpm 12.6.0 explicitly. Do not use a globally drifting Node/pnpm combination when reproducing CI.

## One-time setup

From the repository root:

```bash
cp .env.example .env
uv sync --locked --all-groups
pnpm install --frozen-lockfile
```

On PowerShell:

```powershell
Copy-Item .env.example .env
uv sync --locked --all-groups
pnpm install --frozen-lockfile
```

The root `pnpm-lock.yaml` is the only workspace lockfile. Run pnpm from the repository root so the workspace importer and the frontend package are resolved together. Do not create or commit a second `frontend/pnpm-lock.yaml`; a nested lock can omit platform-specific Rollup packages and reintroduce Windows/CI drift. Builds use the root workspace lock through `pnpm --filter otl-timesheet-pwa`, and `make lock-check` performs an offline-safe consistency check.

Set a random `SESSION_SECRET_KEY` before starting a shared development instance. For tests, `TEST_MODE=true` prevents live catalogue and integration calls; it is not a production configuration.

## Native development

```bash
make dev
```

The command runs the existing cross-platform development runner, which starts FastAPI with reload and Vite with HMR. Equivalent direct commands are:

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pnpm --dir frontend run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to FastAPI. The development server is for one operator; do not expose it to an untrusted network.

## Local Docker development

The explicit HTTP-only development stack is:

```bash
make up-dev
# or
docker compose -f deploy/docker-compose.dev.yml up -d --build
```

It sets `SESSION_COOKIE_SECURE=false`, uses `deploy/nginx/otl-dev.conf`, and binds a local data directory. It is intentionally not the production file. Never expose that port 80 listener to an untrusted network.

Stop it with:

```bash
docker compose -f deploy/docker-compose.dev.yml down
```

## Credential-free checks

The following checks are safe on a fresh checkout and do not call Oracle, OCI, or Redis:

```bash
uv run pytest backend/tests
pnpm --dir frontend run test:unit
pnpm --dir frontend run build
make image-check
make config-dev
```

The container smoke test in CI supplies throwaway test-mode values. The local command `make dev` requires an environment file but permits test-mode placeholders for isolated UI work.

## Live integration testing

Live tests are opt-in and can read or write tenant data. Use a dedicated Fusion test account/person and a test OCI principal. Set the required values through a secret-managed environment, then run:

```bash
RUN_LIVE_INTEGRATIONS=true LIVE_PERSON_NUMBER=<test-person> make test-live
```

Do not set `RUN_LIVE_INTEGRATIONS=true` in ordinary CI, developer shells, or a production `.env` unless the test is explicitly intended. Review the test code before every run and capture only redacted output.

## Troubleshooting

- **`uv` reports a stale lock:** run `uv lock --check`; do not run an unlocked update as a workaround.
- **pnpm reports a stale lock:** remove only the local `node_modules` directory and reinstall from the root with `pnpm install --frozen-lockfile`.
- **Port 8000/5173 is occupied:** stop the conflicting process or use the ports supported by the local runner; do not change production proxy settings ad hoc.
- **Secure cookie is not sent over localhost:** use the development Compose file or set `SESSION_COOKIE_SECURE=false` only for local HTTP. Production always keeps it true.
- **Docker cannot find `.env`:** create it from the template and keep it ignored. Do not paste credentials into Compose YAML.

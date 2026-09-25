.PHONY: help dev preflight preflight-dev preflight-ci smoke test test-backend test-frontend test-e2e test-e2e-chromium test-e2e-matrix test-live coverage lint format format-check typecheck up up-dev down build shell logs status clean config config-dev image-check lock-check verify mobile-build

help:
	@echo "OTL-Voice development and delivery targets"
	@echo "  make help             - Show this help"
	@echo "  make preflight        - Validate production secrets without printing values"
	@echo "  make preflight-dev    - Validate local development configuration"
	@echo "  make smoke            - Run credential-free backend/frontend smoke tests"
	@echo "  make dev              - Start the native backend and Vite development servers"
	@echo "  make test             - Run backend and frontend unit tests"
	@echo "  make test-backend     - Run backend pytest tests"
	@echo "  make test-frontend    - Run frontend Vitest tests"
	@echo "  make test-e2e         - Run the configured Playwright projects"
	@echo "  make test-e2e-chromium - Run only Chromium Playwright tests"
	@echo "  make test-e2e-matrix  - Run Chromium, Firefox, and WebKit tests"
	@echo "  make test-live        - Run opt-in live Oracle/OCI/Redis tests"
	@echo "  make coverage         - Run backend and frontend coverage gates"
	@echo "  make lint             - Run Ruff and ESLint"
	@echo "  make format           - Format backend and frontend source"
	@echo "  make format-check     - Verify formatting without changing files"
	@echo "  make typecheck        - Run mypy and the frontend TypeScript check"
	@echo "  make up               - Start the TLS-first production Compose stack"
	@echo "  make up-dev           - Start the explicit HTTP-only development stack"
	@echo "  make down             - Stop the production Compose stack"
	@echo "  make build            - Build and start the production Compose stack"
	@echo "  make config           - Validate production Compose configuration"
	@echo "  make config-dev       - Validate development Compose configuration"
	@echo "  make image-check      - Run Docker's Dockerfile build check"
	@echo "  make lock-check       - Verify Python and pnpm lockfiles"
	@echo "  make verify           - Run lint, formatting, typecheck, and tests"
	@echo "  make mobile-build     - Build the Capacitor mobile bundle (VITE_API_URL required)"
	@echo "  make clean            - Remove local caches and build artifacts"

preflight:
	$(PYTHON) deploy/preflight.py --env-file .env --mode production
	$(PYTHON) -c "from pathlib import Path; paths=[Path('deploy/nginx/certs/fullchain.pem'),Path('deploy/nginx/certs/privkey.pem'),Path('deploy/secrets/readiness_token')]; missing=[str(p) for p in paths if not p.is_file()]; raise SystemExit('preflight: missing deployment file(s): '+', '.join(missing) if missing else 0)"

preflight-dev:
	$(PYTHON) deploy/preflight.py --env-file .env --mode development

preflight-ci:
	$(PYTHON) deploy/preflight.py --env-file .env --mode ci

smoke:
	$(UV) run pytest backend/tests/test_api.py backend/tests/test_auth.py backend/tests/test_idempotency.py
	$(PNPM) --filter otl-timesheet-pwa exec vitest run

dev: preflight-dev
	$(UV) run python dev_runner.py

test: test-backend test-frontend

test-backend:
	$(UV) run pytest backend/tests

test-frontend:
	$(PNPM) --filter otl-timesheet-pwa run test:unit

test-e2e:
	$(PNPM) --filter otl-timesheet-pwa run test:e2e

test-e2e-chromium:
	$(PNPM) --filter otl-timesheet-pwa exec playwright test --project=chromium

test-e2e-matrix:
	$(PNPM) --filter otl-timesheet-pwa exec playwright test --project=chromium --project=firefox --project=webkit

test-live:
	$(UV) run pytest backend/tests/test_live_integrations.py

coverage:
	$(UV) run pytest backend/tests --cov=backend --cov-report=term-missing --cov-report=xml --cov-fail-under=65
	$(PNPM) --filter otl-timesheet-pwa exec vitest run --coverage --coverage.reporter=text --coverage.reporter=json --coverage.thresholds.statements=75 --coverage.thresholds.lines=75 --coverage.thresholds.functions=75 --coverage.thresholds.branches=70

lint:
	$(UV) run ruff check .
	$(PNPM) --filter otl-timesheet-pwa run lint

format:
	$(UV) run ruff format .
	$(PNPM) --filter otl-timesheet-pwa run format

format-check:
	$(UV) run ruff format --check backend deploy
	$(PNPM) --filter otl-timesheet-pwa exec prettier --check "src/**/*.{ts,tsx}"

typecheck:
	$(UV) run mypy backend
	$(PNPM) --filter otl-timesheet-pwa exec tsc -b tsconfig.app.json tsconfig.node.json
	$(PNPM) --filter otl-timesheet-pwa exec tsc --noEmit --project tsconfig.tests.json

up: preflight config
	$(DOCKER_COMPOSE) -f deploy/docker-compose.yml up -d

up-dev: config-dev
	$(DOCKER_COMPOSE) -f deploy/docker-compose.dev.yml up -d --build

down:
	$(DOCKER_COMPOSE) -f deploy/docker-compose.yml down

build: preflight
	$(DOCKER_COMPOSE) -f deploy/docker-compose.yml up -d --build

shell:
	$(DOCKER_COMPOSE) -f deploy/docker-compose.yml exec app /bin/sh

logs:
	$(DOCKER_COMPOSE) -f deploy/docker-compose.yml logs -f

status:
	$(DOCKER_COMPOSE) -f deploy/docker-compose.yml ps

clean:
	$(PYTHON) -c "import shutil; from pathlib import Path; [shutil.rmtree(p, ignore_errors=True) for p in [Path('__pycache__'), Path('deploy/__pycache__'), Path('.pytest_cache'), Path('.ruff_cache'), Path('.mypy_cache'), Path('htmlcov'), Path('coverage'), Path('frontend/coverage'), Path('frontend/dist'), Path('frontend/test-results'), Path('frontend/playwright-report')]]; [p.unlink(missing_ok=True) for p in [Path('.coverage'), Path('coverage.xml')]]"

config:
	$(DOCKER_COMPOSE) -f deploy/docker-compose.yml config --quiet

config-dev:
	$(DOCKER_COMPOSE) -f deploy/docker-compose.dev.yml config --quiet

image-check:
	docker build --check .

lock-check:
	$(UV) lock --check
	$(PNPM) install --frozen-lockfile --lockfile-only

verify: format-check lint typecheck test

mobile-build:
	$(PNPM) --filter otl-timesheet-pwa run build:mobile

PYTHON ?= python
UV ?= uv
PNPM ?= pnpm
DOCKER_COMPOSE ?= docker compose

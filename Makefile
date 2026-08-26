.PHONY: help dev test test-backend test-frontend test-e2e lint format typecheck up down build shell logs status clean

help:
	@echo "Available commands:"
	@echo "  make dev            - Start local backend & frontend with hot reload"
	@echo "  make test           - Run backend and frontend unit tests"
	@echo "  make test-backend   - Run backend pytest suite"
	@echo "  make test-frontend  - Run frontend vitest suite"
	@echo "  make test-e2e       - Run frontend Playwright E2E tests"
	@echo "  make lint           - Lint backend (ruff) and frontend (eslint)"
	@echo "  make format         - Format backend (ruff) and frontend (prettier)"
	@echo "  make typecheck      - Typecheck backend (mypy) and frontend (tsc)"
	@echo "  make up             - Start production Docker stack"
	@echo "  make down           - Stop Docker stack"
	@echo "  make build          - Rebuild and start Docker stack"
	@echo "  make logs           - View Docker container logs"
	@echo "  make status         - Show Docker container status"
	@echo "  make clean          - Remove caches and build artifacts"

dev:
	@test -f .env || (echo "[warn] .env is missing. Copy .env.example to .env first." && exit 1)
	npx --yes concurrently -c "blue,magenta" -n "BACKEND,FRONTEND" "uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload" "npm --prefix frontend run dev"

test: test-backend test-frontend

test-backend:
	uv run pytest backend/tests

test-frontend:
	npm --prefix frontend run test:unit

test-e2e:
	npm --prefix frontend run test:e2e

lint:
	uv run ruff check .
	npm --prefix frontend run lint

format:
	uv run ruff format .
	npm --prefix frontend run format

typecheck:
	uv run mypy backend
	npm --prefix frontend run typecheck

up:
	@test -f .env || (echo "[warn] .env is missing. Copy .env.example to .env first." && exit 1)
	cd deploy && docker compose up -d
	@echo "Application is available at http://localhost"

down:
	cd deploy && docker compose down

build:
	cd deploy && docker compose up -d --build

shell:
	cd deploy && docker compose exec app bash

logs:
	cd deploy && docker compose logs -f

status:
	cd deploy && docker compose ps

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	rm -rf .coverage htmlcov coverage frontend/coverage frontend/dist


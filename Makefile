.PHONY: all up down build shell logs status

all: up

up:
	@echo "Checking for .env file..."
	@test -f .env || (echo "[warn] .env is missing. Copy .env.example to .env first." && exit 1)
	@echo "Starting the application..."
	cd deploy && docker compose up -d
	@echo "Waiting for services to be ready..."
	@sleep 5
	@echo "Application is available at http://localhost"

down:
	@echo "Stopping and removing the application..."
	cd deploy && docker compose down

build:
	@echo "Building the application..."
	cd deploy && docker compose up -d --build

shell:
	@echo "Opening shell in the app container..."
	cd deploy && docker compose exec app bash

logs:
	cd deploy && docker compose logs -f

status:
	cd deploy && docker compose ps

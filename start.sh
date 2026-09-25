#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: Docker is required for the production stack" >&2
  exit 127
fi
if ! docker info >/dev/null 2>&1; then
  echo "error: Docker daemon is not running" >&2
  exit 1
fi
if [[ ! -f "$ROOT/.env" ]]; then
  echo "error: .env is missing; create it from .env.example" >&2
  exit 2
fi

action="${1:-up}"
case "$action" in
  up)
    docker compose -f "$ROOT/deploy/docker-compose.yml" up -d --build
    echo "Application started at http://localhost"
    ;;
  down)
    docker compose -f "$ROOT/deploy/docker-compose.yml" down
    ;;
  stop)
    docker compose -f "$ROOT/deploy/docker-compose.yml" stop
    ;;
  logs)
    docker compose -f "$ROOT/deploy/docker-compose.yml" logs -f
    ;;
  status|ps)
    docker compose -f "$ROOT/deploy/docker-compose.yml" ps
    ;;
  shell)
    docker compose -f "$ROOT/deploy/docker-compose.yml" exec app sh
    ;;
  *)
    echo "usage: $0 {up|down|stop|logs|status|ps|shell}" >&2
    exit 2
    ;;
esac

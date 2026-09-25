#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v pnpm >/dev/null 2>&1; then
  echo "error: pnpm is required to run the test suite" >&2
  exit 127
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is required to run the test suite" >&2
  exit 127
fi

exec pnpm --dir "$ROOT" run test "$@"

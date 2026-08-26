#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "Running Backend Unit Tests (pytest)..."
uv run pytest backend/tests

echo ""
echo "Running Frontend Unit Tests (vitest)..."
npm --prefix frontend run test:unit

echo ""
echo "========================================="
echo "All unit tests passed successfully!"
echo "========================================="

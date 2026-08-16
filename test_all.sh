#!/bin/bash
set -e

echo "Running Backend Unit Tests (pytest)..."
cd backend
uv run pytest tests/
cd ..

echo "Running Frontend Unit Tests (vitest)..."
cd frontend
npm run test:unit

echo "Running Frontend E2E Tests (Playwright)..."
npm run test:e2e
cd ..

echo "All tests passed successfully!"

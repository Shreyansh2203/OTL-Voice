#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "======================================================="
echo "Starting OTL Timesheet Assistant (Local Dev Mode)"
echo "======================================================="
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "[ERROR] .env file is missing. Please copy .env.example to .env and configure it."
    exit 1
fi

echo "Syncing Python dependencies..."
if ! command -v uv &> /dev/null; then
    echo "[ERROR] 'uv' is not installed. Please install it first."
    exit 1
fi
uv sync

echo ""
echo "Starting both servers with hot-reload enabled..."
echo "(Press CTRL+C in this terminal to stop both servers)"
echo ""

# Use npx concurrently to run both in the same terminal
npx --yes concurrently -c "blue,magenta" -n "BACKEND,FRONTEND" \
  "uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload" \
  "cd frontend && npm run dev"

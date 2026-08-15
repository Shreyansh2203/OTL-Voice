#!/usr/bin/env bash
set -e

echo "Starting the Timesheet Assistant..."

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "[ERROR] Docker daemon is not running. Please start Docker and try again."
    exit 1
fi

if [ ! -f .env ]; then
    echo "[ERROR] .env file is missing. Please copy .env.example to .env and configure it."
    exit 1
fi

cd deploy
docker compose up -d --build

echo ""
echo "======================================================="
echo "Success! The application is running in the background."
echo "Waiting for the server to be fully ready..."
echo "======================================================="

# Wait a few seconds for services to bind
sleep 5

echo "Opening your web browser to http://localhost ..."
if command -v xdg-open > /dev/null; then
    xdg-open http://localhost
elif command -v open > /dev/null; then
    open http://localhost
else
    echo "Please open http://localhost in your browser."
fi

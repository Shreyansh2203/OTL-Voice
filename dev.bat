@echo off
setlocal
cd /d "%~dp0"

echo =======================================================
echo Starting OTL Timesheet Assistant (Local Dev Mode)
echo =======================================================
echo.

REM Check if .env exists
if not exist ".env" (
    echo [ERROR] .env file is missing. Please copy .env.example to .env and configure it.
    pause
    exit /b 1
)

echo Syncing Python dependencies...
uv sync
if %errorlevel% neq 0 (
    echo [WARNING] Failed to sync python dependencies. A background process like your IDE might be locking the virtual environment. Continuing anyway...
)

echo.
echo Starting both servers with hot-reload enabled...
echo (Press CTRL+C in this terminal to stop both servers)
echo.

REM Use npx concurrently to run both in the same terminal
call npx --yes concurrently -c "blue,magenta" -n "BACKEND,FRONTEND" "uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload" "cd frontend && npm run dev"

endlocal

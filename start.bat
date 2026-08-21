@echo off
setlocal
cd /d "%~dp0"

echo Starting the Timesheet Assistant...

REM Check if Docker is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker daemon is not running. Please start Docker Desktop and try again.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env file is missing. Please copy .env.example to .env and configure it.
    pause
    exit /b 1
)

cd deploy
docker compose up -d --build
if %errorlevel% neq 0 (
    echo [ERROR] Failed to start the application via docker compose.
    pause
    exit /b 1
)

echo.
echo =======================================================
echo Success! The application is running in the background.
echo Waiting for the server to be fully ready...
echo =======================================================

REM Wait a few seconds for services to bind
ping 127.0.0.1 -n 6 >nul

echo Opening your web browser to http://localhost ...
start http://localhost

echo.
echo =======================================================
echo Application is running at:
echo   Web App:  http://localhost
echo   API Docs: http://localhost/api/docs
echo =======================================================
echo.
pause

endlocal

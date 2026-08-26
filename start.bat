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

REM Check if subcommands were provided
set "ACTION=%~1"
if /I "%ACTION%"=="down"    goto :do_down
if /I "%ACTION%"=="stop"    goto :do_stop
if /I "%ACTION%"=="logs"    goto :do_logs
if /I "%ACTION%"=="status"  goto :do_status
if /I "%ACTION%"=="ps"      goto :do_status
if /I "%ACTION%"=="shell"   goto :do_shell

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
goto :eof

:do_down
cd deploy
docker compose down
goto :eof

:do_stop
cd deploy
docker compose stop
goto :eof

:do_logs
cd deploy
docker compose logs -f
goto :eof

:do_status
cd deploy
docker compose ps
goto :eof

:do_shell
cd deploy
docker compose exec app bash
goto :eof

endlocal

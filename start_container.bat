@echo off
setlocal

REM ============================================================
REM  OTL Timesheet Assistant - Docker Compose wrapper
REM
REM  Usage:
REM    start_container.bat            Start the stack and attach a shell to the app container.
REM    start_container.bat build      Force-rebuild the images and start the stack.
REM    start_container.bat shell      Open a shell on the running app container.
REM    start_container.bat stop       Stop the stack.
REM    start_container.bat remove     Stop and remove the stack.
REM    start_container.bat logs       Follow container logs.
REM    start_container.bat status     Show stack state.
REM ============================================================

cd /d "%~dp0"
if not exist ".env" (
    echo [warn] .env is missing.
    echo Copy .env.example to .env first.
    pause
    exit /b 1
)
cd deploy

set "ACTION=%~1"
if /I "%ACTION%"=="/?"      goto :usage
if /I "%ACTION%"=="-h"      goto :usage
if /I "%ACTION%"=="--help"  goto :usage
if /I "%ACTION%"=="help"    goto :usage
if /I "%ACTION%"=="build"   goto :build
if /I "%ACTION%"=="shell"   goto :shell
if /I "%ACTION%"=="stop"    goto :stop
if /I "%ACTION%"=="remove"  goto :remove
if /I "%ACTION%"=="down"    goto :remove
if /I "%ACTION%"=="logs"    goto :logs
if /I "%ACTION%"=="status"  goto :status
if /I "%ACTION%"=="ps"      goto :status
if not "%ACTION%"=="" (
    echo Unknown action: %ACTION%
    goto :usage
)

REM Default flow (start and shell)
docker compose up -d
goto :shell

:build
docker compose up -d --build
goto :shell

:shell
echo.
echo API:    http://localhost/api/health
echo Docs:   http://localhost/api/docs
echo Dropping you into a shell inside the app container...
docker compose exec app bash
goto :end

:stop
docker compose stop
goto :end

:remove
docker compose down
goto :end

:logs
docker compose logs -f
goto :end

:status
docker compose ps
goto :end

:usage
echo Usage:
echo   start_container.bat               Start the stack and open a shell.
echo   start_container.bat build         Rebuild images, start the stack, and open a shell.
echo   start_container.bat shell         Open a shell on the already-running app container.
echo   start_container.bat stop          Stop the stack.
echo   start_container.bat remove        Stop AND remove the stack.
echo   start_container.bat logs          Follow container logs.
echo   start_container.bat status        Show stack state.
goto :end

:end
endlocal

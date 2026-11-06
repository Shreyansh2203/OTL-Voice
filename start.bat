@echo off
setlocal
cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo error: Docker is required for the production stack 1>&2
  exit /b 127
)
docker info >nul 2>&1
if errorlevel 1 (
  echo error: Docker daemon is not running 1>&2
  exit /b 1
)
if not exist "%~dp0.env" (
  echo error: .env is missing; create it from .env.example 1>&2
  exit /b 2
)

set "COMPOSE_FILE=%~dp0deploy\docker-compose.yml"
set "ACTION=%~1"
if not defined ACTION set "ACTION=up"
if /I "%ACTION%"=="up" goto :up
if /I "%ACTION%"=="down" goto :down
if /I "%ACTION%"=="stop" goto :stop
if /I "%ACTION%"=="logs" goto :logs
if /I "%ACTION%"=="status" goto :status
if /I "%ACTION%"=="ps" goto :status
if /I "%ACTION%"=="shell" goto :shell

echo usage: %~nx0 {up^|down^|stop^|logs^|status^|ps^|shell} 1>&2
exit /b 2

:up
docker compose -f "%COMPOSE_FILE%" up -d --build
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" exit /b %EXIT_CODE%
echo Application started at http://localhost
exit /b 0

:down
docker compose -f "%COMPOSE_FILE%" down
exit /b %ERRORLEVEL%

:stop
docker compose -f "%COMPOSE_FILE%" stop
exit /b %ERRORLEVEL%

:logs
docker compose -f "%COMPOSE_FILE%" logs -f
exit /b %ERRORLEVEL%

:status
docker compose -f "%COMPOSE_FILE%" ps
exit /b %ERRORLEVEL%

:shell
docker compose -f "%COMPOSE_FILE%" exec app sh
exit /b %ERRORLEVEL%

@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  OTL Timesheet Assistant - container launcher (Docker)
REM
REM  Usage:
REM    start_container.bat            Smart start. Builds the image if missing,
REM                                   creates the container if missing, starts it
REM                                   if stopped, then drops into a shell.
REM    start_container.bat build      Force-rebuild the image (re-creates container).
REM    start_container.bat shell      Just exec a shell on the running container.
REM    start_container.bat stop       Stop the container (keep it for fast restart).
REM    start_container.bat remove     Stop AND remove the container.
REM    start_container.bat logs       Follow container logs (Ctrl+C exits).
REM    start_container.bat status     Show container state.
REM ============================================================

REM -------- SETTINGS --------
set "IMAGE=otl:latest"
set "CONTAINER_NAME=otl"
REM uvicorn (FastAPI) listens on 8000 inside the container (see Containerfile CMD).
set "HOST_PORT=8000"
set "CONTAINER_PORT=8000"
set "WORKDIR=/app"
set "ENV_FILE=.env"
REM Build file is named Containerfile, so Docker needs -f to find it.
set "DOCKERFILE=Containerfile"

REM Run from the directory this .bat lives in, regardless of where it's invoked from.
cd /d "%~dp0"
set "HOST_PATH=%cd%"

REM Convert backslashes to forward slashes (C:\Projects\OTL -> C:/Projects/OTL).
REM Docker Desktop accepts that form directly for -v bind mounts.
set "DOCKER_PATH=%HOST_PATH:\=/%"

REM -------- Dispatch on first arg --------
set "ACTION=%~1"
if /I "%ACTION%"=="/?"      goto :usage
if /I "%ACTION%"=="-h"      goto :usage
if /I "%ACTION%"=="--help"  goto :usage
if /I "%ACTION%"=="help"    goto :usage
if /I "%ACTION%"=="build"   goto :build
if /I "%ACTION%"=="rebuild" goto :build
if /I "%ACTION%"=="shell"   goto :shell_only
if /I "%ACTION%"=="stop"    goto :stop
if /I "%ACTION%"=="remove"  goto :remove
if /I "%ACTION%"=="down"    goto :remove
if /I "%ACTION%"=="logs"    goto :logs
if /I "%ACTION%"=="status"  goto :status
if /I "%ACTION%"=="ps"      goto :status
if not "%ACTION%"=="" (
    echo Unknown action: %ACTION%
    echo.
    goto :usage
)

REM -------- Default flow --------
echo ============================================================
echo  OTL Timesheet Assistant - container launcher
echo    image      : %IMAGE%
echo    container  : %CONTAINER_NAME%
echo    host path  : %HOST_PATH%
echo    mount      : %DOCKER_PATH%  ^-^>  %WORKDIR%
echo    port       : %HOST_PORT% (host) ^-^>  %CONTAINER_PORT% (container)
echo ============================================================

if not exist "%ENV_FILE%" (
    echo.
    echo [warn] %ENV_FILE% is missing in %HOST_PATH%.
    echo        OCI credentials will not be available inside the container.
    echo        Copy .env.example to .env and fill in your OCI values first.
    echo.
    pause
    exit /b 1
)

REM Build image if missing.
docker image inspect %IMAGE% >NUL 2>&1
if errorlevel 1 (
    echo Image %IMAGE% not found. Building...
    docker build -f %DOCKERFILE% -t %IMAGE% .
    if errorlevel 1 (
        echo [start_container] image build failed.
        pause
        exit /b 1
    )
) else (
    echo Image %IMAGE% present. Skipping build. Use "start_container.bat build" to force rebuild.
)

REM Does a container with this name already exist?
docker ps -a -q -f "name=^%CONTAINER_NAME%$" | findstr . >NUL
if !ERRORLEVEL! equ 0 (
    REM Container exists. Running or stopped?
    for /f "delims=" %%i in ('docker inspect -f "{{.State.Status}}" %CONTAINER_NAME%') do set "STATUS=%%i"
    if /I "!STATUS!"=="running" (
        echo Container %CONTAINER_NAME% is already running. Attaching shell...
    ) else (
        echo Container %CONTAINER_NAME% exists but is !STATUS!. Starting...
        docker start %CONTAINER_NAME% >NUL
        if errorlevel 1 (
            echo [start_container] docker start failed.
            pause
            exit /b 1
        )
        REM Brief wait for uvicorn to bind before we attach.
        ping -n 3 127.0.0.1 >NUL
    )
) else (
    echo Creating new container %CONTAINER_NAME%...
    docker run -d ^
        --name %CONTAINER_NAME% ^
        --env-file "%ENV_FILE%" ^
        -v "%DOCKER_PATH%:%WORKDIR%" ^
        -w %WORKDIR% ^
        -p %HOST_PORT%:%CONTAINER_PORT% ^
        --restart unless-stopped ^
        %IMAGE%
    if errorlevel 1 (
        echo [start_container] docker run failed.
        pause
        exit /b 1
    )
    REM Server boot delay.
    ping -n 4 127.0.0.1 >NUL
)

goto :shell

:build
echo Force-rebuilding %IMAGE%...
docker build -f %DOCKERFILE% -t %IMAGE% .
if errorlevel 1 (
    echo [start_container] image build failed.
    pause
    exit /b 1
)
REM Re-create the container so it picks up the fresh image.
docker rm -f %CONTAINER_NAME% >NUL 2>&1
echo Creating new container %CONTAINER_NAME%...
docker run -d ^
    --name %CONTAINER_NAME% ^
    --env-file "%ENV_FILE%" ^
    -v "%DOCKER_PATH%:%WORKDIR%" ^
    -w %WORKDIR% ^
    -p %HOST_PORT%:%CONTAINER_PORT% ^
    --restart unless-stopped ^
    %IMAGE%
if errorlevel 1 (
    echo [start_container] docker run failed.
    pause
    exit /b 1
)
timeout /t 3 >NUL
goto :shell

:shell_only
docker ps -q -f "name=^%CONTAINER_NAME%$" | findstr . >NUL
if errorlevel 1 (
    echo Container %CONTAINER_NAME% is not running. Use "start_container.bat" first.
    exit /b 1
)
goto :shell

:shell
echo.
echo API:    http://localhost:%HOST_PORT%/api/health
echo Docs:   http://localhost:%HOST_PORT%/docs
echo Dropping you into a shell inside the container.
echo Type 'exit' to leave the shell. The container keeps running in the background.
echo Stop later with: start_container.bat stop    Remove with: start_container.bat remove
echo.
docker exec -it %CONTAINER_NAME% bash -lc "cd %WORKDIR% && exec bash"
goto :end

:stop
echo Stopping %CONTAINER_NAME%...
docker stop %CONTAINER_NAME%
goto :end

:remove
echo Stopping and removing %CONTAINER_NAME%...
docker rm -f %CONTAINER_NAME%
goto :end

:logs
echo Tailing %CONTAINER_NAME% logs. Press Ctrl+C to stop.
docker logs -f %CONTAINER_NAME%
goto :end

:status
docker ps -a -f "name=^%CONTAINER_NAME%$"
goto :end

:usage
echo Usage:
echo   start_container.bat               Smart start (build if missing, create if missing, start if stopped), then open a shell.
echo   start_container.bat build         Force-rebuild image and re-create container, then open a shell.
echo   start_container.bat shell         Open a shell on the already-running container.
echo   start_container.bat stop          Stop the container (keep it for fast restart).
echo   start_container.bat remove        Stop AND remove the container.
echo   start_container.bat logs          Follow container logs.
echo   start_container.bat status        Show container state.
goto :end

:end
endlocal

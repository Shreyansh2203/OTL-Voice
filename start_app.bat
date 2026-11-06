@echo off
setlocal
cd /d "%~dp0"

where pnpm >nul 2>&1
if errorlevel 1 (
  echo error: pnpm is required for local development 1>&2
  exit /b 127
)
where uv >nul 2>&1
if errorlevel 1 (
  echo error: uv is required for local development 1>&2
  exit /b 127
)

call pnpm run dev %*
set "EXIT_CODE=%ERRORLEVEL%"
exit /b %EXIT_CODE%

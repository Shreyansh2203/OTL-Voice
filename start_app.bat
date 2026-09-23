@echo off
cd /d "%~dp0"
title OTL Voice - Development Server
echo ===================================================
echo Booting OTL Voice using Native Python Orchestrator...
echo ===================================================
echo.

set "UV_PROJECT_ENVIRONMENT=.venv2"
uv run python dev_runner.py

pause

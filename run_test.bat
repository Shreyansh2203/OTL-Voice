@echo off
title OTL Voice - Diagnostic Test
echo ===================================================
echo Running OTL Voice End-to-End Diagnostic Test...
echo ===================================================
echo.

:: Ensure uv uses the correct virtual environment
set "UV_PROJECT_ENVIRONMENT=.venv2"

:: Run the python test script using uv
uv run python test_e2e.py

echo.
echo ===================================================
pause

@echo off
setlocal
cd /d "%~dp0"

echo Running Backend Unit Tests (pytest)...
call uv run pytest backend/tests
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Backend tests failed!
    exit /b %ERRORLEVEL%
)

echo.
echo Running Frontend Unit Tests (vitest)...
cd frontend
call npm run test:unit
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Frontend unit tests failed!
    exit /b %ERRORLEVEL%
)
cd ..

echo.
echo =========================================
echo All unit tests passed successfully!
echo =========================================
endlocal

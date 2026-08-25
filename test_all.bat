@echo off
echo Running Backend Unit Tests (pytest)...
cd backend
uv run pytest tests/
if %ERRORLEVEL% NEQ 0 (
    echo Backend tests failed!
    exit /b %ERRORLEVEL%
)
cd ..

echo Running Frontend Unit Tests (vitest)...
cd frontend
call npm run test:unit
if %ERRORLEVEL% NEQ 0 (
    echo Frontend unit tests failed!
    exit /b %ERRORLEVEL%
)

echo Running Frontend E2E Tests (Playwright)...
call npm run test:e2e
if %ERRORLEVEL% NEQ 0 (
    echo Frontend E2E tests failed!
    exit /b %ERRORLEVEL%
)
cd ..

echo All tests passed successfully!

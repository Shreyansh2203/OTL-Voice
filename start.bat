@echo off
echo Starting the Timesheet Assistant...
cd deploy
docker compose up -d
echo.
echo =======================================================
echo Success! The application is running in the background.
echo Opening your web browser to http://localhost ...
echo =======================================================
start http://localhost

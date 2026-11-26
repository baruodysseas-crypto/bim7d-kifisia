@echo off
cd /d "%~dp0"
echo Starting the 7D-BIM tool in Docker (first time: 5-10 minutes)...
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo Docker did not start. Open Docker Desktop, wait for "Engine running" and try again.
  pause
  exit /b 1
)
echo Waiting for the app...
timeout /t 8 /nobreak >nul
start "" http://localhost:8000
echo.
echo The app runs at http://localhost:8000  -  to stop it, run docker_stop.bat
pause

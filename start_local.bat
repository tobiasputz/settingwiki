@echo off
setlocal
cd /d "%~dp0"
where docker >nul 2>nul
if errorlevel 1 (
  echo Docker was not found. Install Docker Desktop first.
  pause
  exit /b 1
)
echo.
echo Starting Loreforge at http://127.0.0.1:8000
if "%ADMIN_PASSWORD%"=="" echo Local editor password: loreforge
 echo Press Ctrl+C to stop the server.
echo.
docker compose up --build

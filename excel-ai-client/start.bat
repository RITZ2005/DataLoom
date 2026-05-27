@echo off
REM This file starts the frontend only
REM For full system startup, use the root start.bat

cd /d "%~dp0"

echo.
echo ============================================
echo Excel AI Client - Frontend Startup
echo ============================================
echo.

echo.
echo Starting Vue Frontend (Port 8080)
echo ============================================
echo.
echo Make sure the backend is running at http://localhost:8000
echo.

call npm run dev

echo.
echo Frontend stopped.
echo.

pause

@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo ==========================================
echo    Excel AI System - Full Setup ^& Start
echo ==========================================

echo.
echo [1/7] Checking prerequisite commands...
where docker >nul 2>&1 || (echo ERROR: docker is not installed. & exit /b 1)
where python >nul 2>&1 || (echo ERROR: python is not installed. & exit /b 1)
where npm >nul 2>&1 || (echo ERROR: npm is not installed. & exit /b 1)

echo.
echo [2/7] Setting up Databases (PostgreSQL pgvector ^& Redis)...
docker network inspect shared_db_network >nul 2>&1
if errorlevel 1 (
    echo Creating shared docker network...
    docker network create shared_db_network >nul
)

docker ps -a --format "{{.Names}}" | findstr /R /C:"^pg16$" >nul
if errorlevel 1 (
    echo Starting new pg16 container with pgvector...
    docker run -d --name pg16 --network shared_db_network -p 5433:5432 -e POSTGRES_PASSWORD=pgvector -v pg16_data:/var/lib/postgresql/data pgvector/pgvector:pg16 >nul
    echo Waiting 10 seconds for PostgreSQL to initialize...
    timeout /t 10 /nobreak >nul
) else (
    echo pg16 container already exists. Ensuring it is running...
    docker start pg16 >nul
)

docker ps -a --format "{{.Names}}" | findstr /R /C:"^redis$" >nul
if errorlevel 1 (
    echo Starting new redis container...
    docker run -d --name redis --network shared_db_network -p 6379:6379 redis:alpine >nul
) else (
    echo redis container already exists. Ensuring it is running...
    docker start redis >nul
)

echo Creating hybrid database and vector extension if they don't exist...
docker exec pg16 psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='hybrid'" | findstr /R /C:"1" >nul
if errorlevel 1 (
    docker exec pg16 psql -U postgres -d postgres -c "CREATE DATABASE hybrid;" >nul
    docker exec pg16 psql -U postgres -d hybrid -c "CREATE EXTENSION IF NOT EXISTS vector;" >nul
) else (
    echo hybrid database already exists. Ensuring pgvector extension...
    docker exec pg16 psql -U postgres -d hybrid -c "CREATE EXTENSION IF NOT EXISTS vector;" >nul
)

echo.
echo [3/7] Setting up Langfuse...
cd excel-ai-server-api
call start-langfuse.bat
cd ..

echo.
echo [4/7] Setting up Backend Python Environment...
cd excel-ai-server-api
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)
echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing backend requirements...
pip install -r requirements.txt

echo Running PG Role Setup...
python setup_pg_role.py
cd ..

echo.
echo [5/7] Starting Backend API...
start "Excel AI Backend" cmd /k "cd excel-ai-server-api && call venv\Scripts\activate.bat && uvicorn main:app --reload --host 0.0.0.0 --port 8000"

echo.
echo [6/7] Setting up Frontend Configuration...
cd excel-ai-client
echo Installing frontend dependencies...
call npm install
cd ..

echo.
echo [7/7] Starting Frontend Client...
start "Excel AI Frontend" cmd /k "cd excel-ai-client && npm run dev"

echo.
echo ==========================================
echo   Setup Complete! System is starting...
echo ==========================================
echo Backend API : http://localhost:8000/docs
echo Frontend UI : Usually http://localhost:5173 (Check Frontend window)
echo Langfuse UI : http://localhost:3000
echo.
echo Press any key to close this installer window (Backend and Frontend will keep running in their own windows).
pause >nul

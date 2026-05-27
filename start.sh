#!/bin/bash
set -e

echo "=========================================="
echo "   Excel AI System - Full Setup & Start"
echo "=========================================="

echo ""
echo "[1/7] Checking prerequisite commands..."
command -v docker >/dev/null 2>&1 || { echo >&2 "ERROR: docker is not installed. Aborting."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo >&2 "ERROR: python3 is not installed. Aborting."; exit 1; }
command -v npm >/dev/null 2>&1 || { echo >&2 "ERROR: npm is not installed. Aborting."; exit 1; }

echo ""
echo "[2/7] Setting up Databases (PostgreSQL pgvector & Redis)..."
if ! docker network inspect shared_db_network >/dev/null 2>&1; then
    echo "Creating shared docker network..."
    docker network create shared_db_network >/dev/null
fi

if ! docker ps -a --format '{{.Names}}' | grep -Eq "^pg16$"; then
    echo "Starting new pg16 container with pgvector..."
    docker run -d --name pg16 --network shared_db_network -p 5433:5432 -e POSTGRES_PASSWORD=pgvector -v pg16_data:/var/lib/postgresql/data pgvector/pgvector:pg16 >/dev/null
    echo "Waiting 10 seconds for PostgreSQL to initialize..."
    sleep 10
else
    echo "pg16 container already exists. Ensuring it is running..."
    docker start pg16 >/dev/null
fi

if ! docker ps -a --format '{{.Names}}' | grep -Eq "^redis$"; then
    echo "Starting new redis container..."
    docker run -d --name redis --network shared_db_network -p 6379:6379 redis:alpine >/dev/null
else
    echo "redis container already exists. Ensuring it is running..."
    docker start redis >/dev/null
fi

echo "Creating hybrid database and vector extension if they don't exist..."
if ! docker exec pg16 psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='hybrid'" | grep -q 1; then
    docker exec pg16 psql -U postgres -d postgres -c "CREATE DATABASE hybrid;" >/dev/null
    docker exec pg16 psql -U postgres -d hybrid -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
else
    echo "hybrid database already exists. Ensuring pgvector extension..."
    docker exec pg16 psql -U postgres -d hybrid -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
fi

echo ""
echo "[3/7] Setting up Langfuse..."
cd excel-ai-server-api
echo "Ensuring langfuse DB inside existing pg16 container if missing..."
if ! docker exec pg16 psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='langfuse'" | grep -q 1; then
    docker exec pg16 psql -U postgres -d postgres -c "CREATE DATABASE langfuse;" >/dev/null
fi

echo "Starting Langfuse stack..."
docker compose -f docker-compose-langfuse.yml up -d
cd ..

echo ""
echo "[4/7] Setting up Backend Python Environment..."
cd excel-ai-server-api
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
echo "Installing backend requirements..."
pip install -r requirements.txt

echo "Running PG Role Setup..."
python3 setup_pg_role.py
cd ..

echo ""
echo "[5/7] Starting Backend API..."
cd excel-ai-server-api
uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

echo ""
echo "[6/7] Setting up Frontend Configuration..."
cd excel-ai-client
echo "Installing frontend dependencies..."
npm install
cd ..

echo ""
echo "[7/7] Starting Frontend Client..."
cd excel-ai-client

# Cleanup background processes on script exit
trap "echo 'Shutting down...'; kill $BACKEND_PID; exit" INT TERM EXIT

echo ""
echo "=========================================="
echo "   Setup Complete! System is running..."
echo "=========================================="
echo "Backend API : http://localhost:8000/docs"
echo "Langfuse UI : http://localhost:3000"
echo "Frontend UI : Starting now (keeps terminal busy)..."
echo "Press Ctrl+C to stop both backend and frontend."
echo ""

npm run dev

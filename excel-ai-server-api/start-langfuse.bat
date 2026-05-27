@echo off
setlocal EnableExtensions EnableDelayedExpansion
set DB_CREATED=0

echo [1/6] Ensuring shared Docker network exists...
docker network inspect shared_db_network >nul 2>&1
if errorlevel 1 (
  docker network create shared_db_network >nul
  if errorlevel 1 (
    echo Failed to create shared_db_network
    exit /b 1
  )
)

echo [2/6] Ensuring pg16 is connected to shared network...
docker network connect shared_db_network pg16 >nul 2>&1

echo [3/6] Ensuring redis is connected to shared network...
docker network connect shared_db_network redis >nul 2>&1

echo [4/6] Creating langfuse DB inside existing pg16 container if missing...
docker exec pg16 psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='langfuse'" | findstr /R /C:"1" >nul
if errorlevel 1 (
  docker exec pg16 psql -U postgres -d postgres -c "CREATE DATABASE langfuse;"
  if errorlevel 1 (
    echo Failed to create langfuse database.
    exit /b 1
  )
  set DB_CREATED=1
  echo langfuse database created.
) else (
  echo langfuse database already exists.
)

echo [5/6] Starting Langfuse stack...
if "!DB_CREATED!"=="1" (
  docker compose -f docker-compose-langfuse.yml up -d --force-recreate
) else (
  docker compose -f docker-compose-langfuse.yml up -d
)
if errorlevel 1 (
  echo Failed to start Langfuse stack.
  exit /b 1
)

echo [6/6] Checking Langfuse bootstrap state...
set ORG_COUNT=NA
set PROJ_COUNT=NA
set KEY_COUNT=NA
set ORG_ID=
set PROJ_ID=
docker exec pg16 psql -U postgres -d langfuse -c "\dt organizations" 2>nul | findstr /I "organizations" >nul
if errorlevel 1 (
  echo.
  echo Langfuse tables are not ready yet. Wait 10-20 seconds and run this script again.
) else (
  for /f %%A in ('docker exec pg16 psql -U postgres -d langfuse -tAc "SELECT COUNT(*) FROM organizations"') do set ORG_COUNT=%%A
  for /f %%A in ('docker exec pg16 psql -U postgres -d langfuse -tAc "SELECT COUNT(*) FROM projects"') do set PROJ_COUNT=%%A
  for /f %%A in ('docker exec pg16 psql -U postgres -d langfuse -tAc "SELECT COUNT(*) FROM api_keys"') do set KEY_COUNT=%%A
  for /f %%A in ('docker exec pg16 psql -U postgres -d langfuse -tAc "SELECT COALESCE((SELECT id FROM organizations ORDER BY created_at ASC LIMIT 1), '')"') do set ORG_ID=%%A
  for /f %%A in ('docker exec pg16 psql -U postgres -d langfuse -tAc "SELECT COALESCE((SELECT id FROM projects ORDER BY created_at ASC LIMIT 1), '')"') do set PROJ_ID=%%A

  echo Org count: !ORG_COUNT! ^| Project count: !PROJ_COUNT! ^| API key count: !KEY_COUNT!
  if not "!ORG_ID!"=="" echo Detected ORG_ID: !ORG_ID!
  if not "!PROJ_ID!"=="" echo Detected PROJECT_ID: !PROJ_ID!

  if "!KEY_COUNT!"=="0" (
  echo.
  echo No API keys found yet.
  echo Backend bootstrap now auto-creates admin, org, and project.
  echo Only remaining manual step:
  echo 1^) Create one project API key in Langfuse UI and copy pk-lf/sk-lf to .env
  if not "!ORG_ID!"=="" echo 2^) Optional: set LANGFUSE_ORG_ID=!ORG_ID! and LANGFUSE_PROJECT_ID=!PROJ_ID! in .env
  if "!ORG_ID!"=="" echo 2^) Optional: keep LANGFUSE_ORG_ID and LANGFUSE_PROJECT_ID empty; backend will auto-detect on startup
  echo 3^) Restart backend: uvicorn main:app --reload --host 0.0.0.0 --port 8000
  )
)

echo Done. Langfuse stack is up.
echo Open http://localhost:3000
exit /b 0

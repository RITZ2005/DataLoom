# Excel Intelligence System

Monorepo for an AI-powered analytics platform that started as Excel and CSV file analysis and has grown into a broader data workspace product with ETL, semantic modeling, dashboards, reports, public sharing, and Langfuse-backed observability.

This README reflects the current repository state as of May 20, 2026.

## Current Status

The project is active and already supports two major product layers:

- A legacy file-centric workflow for uploading spreadsheets, previewing data, chatting over files, and generating dashboards.
- A newer workspace-centric workflow for ingesting external databases through ETL, profiling tables, defining semantic metadata, chatting with warehouse-style data, building dashboards, and sharing reports publicly.

Today the repo contains:

- A Vue 3 + Vite frontend in `excel-ai-client/`
- A FastAPI backend in `excel-ai-server-api/`
- Auth, admin, projects, boards, ETL, workspaces, public sharing, and Langfuse integration
- Deep internal documentation in `docs/`

## Product Areas

### 1. Document Intelligence

- Upload CSV and Excel files
- Support multi-sheet Excel extraction
- Preview rows, statistics, chat history, and saved questions
- Run natural-language queries through the legacy file agent
- Generate dashboards, widgets, comparisons, and chart-builder views

### 2. Projects And Insight Boards

- Organize files into projects and subprojects
- Maintain dashboard-first project views
- Create standalone Insight Boards
- Switch active files while preserving dashboard templates
- Publish and publicly share board or project dashboards

### 3. ETL Pipelines

- Connect to SQL and Mongo-style external data sources
- Preview source tables
- Generate transform scripts
- Run dry-runs on sample data
- Execute full ETL jobs into PostgreSQL workspaces
- Poll jobs, edit jobs, and run incremental syncs

### 4. Workspaces

- Create isolated PostgreSQL-backed workspaces
- Browse tables, columns, descriptions, and relationships
- Auto-profile tables and enrich semantic metadata
- Define metrics, dimensions, and synonyms
- Chat with workspace data through the RAG-to-SQL flow
- Create reports, summaries, dashboards, custom widgets, and public share links

### 5. Observability And Sharing

- JWT-based auth and admin user management
- Public share routes for dashboards, workspace reports, and shared workspace chat
- Optional Langfuse tracing with backend SSO bridge
- Redis-backed semantic cache and Langfuse session persistence

## Repository Layout

```text
pandas triagent system/
|-- docs/
|   |-- CODEBASE_FULL_WALKTHROUGH.md
|   |-- BACKEND_ARCHITECTURE_REPORT.md
|   `-- UNDOCUMENTED_APIs.md
|-- excel-ai-client/
|   |-- src/
|   |   |-- pages/
|   |   |-- router/
|   |   `-- services/
|   |-- package.json
|   `-- vite.config.ts
|-- excel-ai-server-api/
|   |-- app/
|   |   |-- core/
|   |   |-- routers/
|   |   |-- schemas/
|   |   `-- services/
|   |-- main.py
|   |-- requirements.txt
|   |-- docker-compose-langfuse.yml
|   `-- start-langfuse.bat
`-- README.md
```

## Backend Snapshot

The FastAPI app lives in [excel-ai-server-api/main.py](excel-ai-server-api/main.py) and currently registers these router modules:

- `admin`
- `auth`
- `boards`
- `categories`
- `chat`
- `dashboard`
- `etl`
- `export`
- `files`
- `health`
- `langfuse_share`
- `preview`
- `projects`
- `query`
- `workspace`

These cover the full platform surface: authentication, file ingestion, dashboards, ETL, workspaces, public sharing, and support endpoints.

## Frontend Snapshot

The Vue app currently ships routes for:

- Login and registration
- Documents and uploads
- File chat
- Smart dashboard
- Project dashboards and board dashboards
- ETL pipeline UI
- Workspace list, catalog, chat, dashboard, and report pages
- Public shared dashboard, shared workspace, and shared report pages

Vite development defaults to port `8080`, and `/api` is proxied to the backend on `http://localhost:8000`.

## Tech Stack

### Frontend

- Vue 3
- TypeScript
- Vite
- Tailwind CSS
- Pinia
- GridStack
- ECharts and Chart.js
- Axios

### Backend

- FastAPI
- Uvicorn
- Pandas
- PostgreSQL
- pgvector
- Redis
- LangChain
- OpenAI, Ollama, or OpenWebUI-backed LLM access
- Langfuse

## Local Development

### Prerequisites

- Python `3.9+`
- Node.js `18+`
- PostgreSQL with `pgvector`
- Redis recommended
- One LLM provider configured: OpenAI, Ollama, or OpenWebUI
- Optional: Langfuse for tracing and SSO

### 1. Start The Backend

```bash
cd excel-ai-server-api
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Backend base URL:

```text
http://localhost:8000
```

### 2. Start The Frontend

```bash
cd excel-ai-client
npm install
npm run dev
```

Frontend dev URL:

```text
http://localhost:8080
```

### 3. Optional Langfuse Stack

From `excel-ai-server-api/`:

```bash
start-langfuse.bat
```

Or manually:

```bash
docker network create shared_db_network
docker network connect shared_db_network pg16
docker network connect shared_db_network redis
docker exec pg16 psql -U postgres -d postgres -c "CREATE DATABASE langfuse;"
docker compose -f docker-compose-langfuse.yml up -d
```

Langfuse default local URL:

```text
http://localhost:3000
```

## Environment Variables

### Backend `.env`

Create `excel-ai-server-api/.env` with values appropriate to your environment.

```env
PG_HOST=localhost
PG_PORT=5432
PG_DATABASE=hybrid
PG_USER=postgres
PG_PASSWORD=your-password

LLM_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL_NAME=gpt-4o

OLLAMA_BASE_URL=http://localhost:11434

OPENWEBUI_BASE_URL=http://localhost:8080
OPENWEBUI_API_KEY=your-openwebui-key

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

LANGFUSE_ENABLED=true
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=your-langfuse-public-key
LANGFUSE_SECRET_KEY=your-langfuse-secret-key
LANGFUSE_ADMIN_EMAIL=admin@example.com
LANGFUSE_ADMIN_PASSWORD=change-me
LANGFUSE_ORG_ID=
LANGFUSE_PROJECT_ID=
```

Notes:

- `PG_*` is required.
- Redis is strongly recommended for semantic cache and Langfuse cookie persistence.
- Langfuse is optional. If you do not need it, set `LANGFUSE_ENABLED=false`.
- The backend supports multiple LLM providers, but you only need to configure the one you actually use.

### Frontend `.env`

Create `excel-ai-client/.env` if you want explicit local overrides:

```env
VITE_API_URL=http://localhost:8000
VITE_API_BASE_URL=http://localhost:8000
VITE_LANGFUSE_HOST=http://localhost:3000
VITE_LANGFUSE_PROJECT_ID=
VITE_SHARE_BASE_URL=http://localhost:8080
```

Notes:

- `VITE_API_URL` is used by the main Axios client.
- `VITE_API_BASE_URL` is also useful because workspace streaming code references it directly.
- If omitted during local dev, the Vite proxy still handles `/api`, but setting both variables avoids mismatch between request styles.

## Main User Flows

### Legacy File Flow

1. Register or log in.
2. Upload a CSV or Excel file.
3. Preview rows and statistics.
4. Ask file-based questions in chat.
5. Generate a dashboard or custom widgets.

### ETL To Workspace Flow

1. Create a workspace.
2. Connect an external database from the ETL page.
3. Preview source tables.
4. Generate or edit a transform script.
5. Run dry-run or full ETL.
6. Open the workspace catalog, chat, report, or dashboard pages.

### Public Sharing Flow

1. Share a project, board, workspace dashboard, or workspace report.
2. Use the generated tokenized public URL.
3. Consumers open the shared page without platform login.

## Useful Commands

### Backend

```bash
cd excel-ai-server-api
venv\Scripts\activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd excel-ai-client
npm run dev
npm run build
npm run lint
npm run type-check
```

## Documentation

- [Full Codebase Walkthrough](docs/CODEBASE_FULL_WALKTHROUGH.md)
- [Backend Architecture Report](docs/BACKEND_ARCHITECTURE_REPORT.md)
- [Backend Setup Instructions](excel-ai-server-api/SETUP_INSTRUCTIONS.md)
- [Backend Quick Start](excel-ai-server-api/QUICK_START_GUIDE.md)
- [Backend Project Structure](excel-ai-server-api/PROJECT_STRUCTURE.md)

## Important Notes

- The older file-centric analytics stack is still active and supported.
- The workspace and ETL stack is now the larger and more advanced product area.
- The backend and frontend subfolder READMEs are not the best project-level source of truth right now; use this root README and the docs folder first.
- Public sharing and Langfuse SSO rely on correct host configuration when deployed outside localhost.

## Health Checks

Useful endpoints once the backend is running:

- `GET /health`
- `GET /api/info`

## Recommended Reading Order

If you are new to the repo:

1. Read this `README.md`
2. Read `excel-ai-server-api/PROJECT_STRUCTURE.md`
3. Read `docs/BACKEND_ARCHITECTURE_REPORT.md`
4. Read `docs/CODEBASE_FULL_WALKTHROUGH.md`

## Project Status

Current status: active internal platform with implemented auth, file analytics, projects, boards, ETL pipelines, workspaces, report sharing, and Langfuse integration.

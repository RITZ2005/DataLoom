# Deployment & Infrastructure Architecture

## Overview
This document outlines the infrastructure, deployment configurations, and operational logic required to run the Excel AI Server and Client in various environments (Development vs. Production), highlighting containerization, environment variables, and observability stacks.

---

## 1. Local Development & Scripts

### Startup Orchestration (`start-langfuse.bat` / `main.py`)
For local Windows development, the environment heavily utilizes batch scripting and direct Python execution.

- **`start-langfuse.bat`:** Automatically pulls and starts the Langfuse telemetry and PostgreSQL Docker containers using the `docker-compose-langfuse.yml` configuration.
- **FastAPI Startup (`main.py`):** Uses `uvicorn` to host the backend API.
  - Automatically checks for the presence of the `production_system.log` and configures the `HybridSystem` logger.
  - Performs an initial boot-check to ensure Langfuse environment variables (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) are present, otherwise graceful fallback to standard logging is activated.

### Frontend Development
- The Vue client is run using `npm run dev` (Vite dev server).
- **Proxying:** `vite.config.ts` is configured to proxy all `/api` requests to the local Uvicorn instance (e.g., `http://localhost:8000`), avoiding CORS issues during local development.

---

## 2. Infrastructure Services (Docker Compose)

### `docker-compose-langfuse.yml`
This file defines the isolated infrastructure stack needed for telemetry and database caching.

1. **PostgreSQL (pgvector):**
   - **Role:** Primary relational data store and Vector DB.
   - **Extension:** Requires the `pgvector` extension to be enabled (`CREATE EXTENSION vector;`) via the `setup_pg_role.py` or init scripts.
2. **Redis:**
   - **Role:** Semantic caching and fast session storage.
3. **Langfuse:**
   - **Role:** Comprehensive LLM observability platform. Captures traces, tokens, and latencies from the Hybrid Agent to calculate cost and debug prompts.

---

## 3. Environment Configuration (`.env`)

A secure, centralized `.env` file controls the behavioral toggles of the system.

### Key Environment Groups:
- **LLM Configuration:**
  - `OPENAI_API_KEY` / `OLLAMA_HOST`: Determines which LLM provider the agent network defaults to.
  - `EMBEDDING_MODEL`: Specific model to use for vectorizing the text (e.g., `text-embedding-3-small`).
- **Database & Cache:**
  - `DATABASE_URL`: Connection string for SQLAlchemy (PostgreSQL).
  - `REDIS_URL`: Connection string for the RediSearch cache.
- **Observability:**
  - `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`: Binds the FastAPI application to the telemetry backend.
- **Security:**
  - `JWT_SECRET`: Cryptographic key for signing user sessions.
  - `ADMIN_SECRET_KEY`: Overrides for generating initial admin profiles.

---

## 4. Production Considerations (Deployment Guide)

To transition this system into a production environment (e.g., AWS, GCP, or generic Kubernetes), the following architectural changes must be considered:

### A. Reverse Proxy & SSL (Nginx / Traefik)
- **Role:** Expose the application via HTTPS.
- **Configuration:** Needs to appropriately proxy WebSockets and HTTP/2 for Server-Sent Events (SSE) to ensure chat streams and file upload progress bars work under high load.

### B. Database Migrations
- Currently, the application might rely on SQLAlchemy's `create_all()` or ad-hoc `ALTER TABLE` statements (as seen in older routers).
- **Production Requirement:** Implementation of **Alembic** to manage robust, version-controlled schema migrations for PostgreSQL.

### C. Containerizing the Application
- The FastAPI backend and Vue frontend should each have their own `Dockerfile`.
  - **Backend:** Based on `python:3.11-slim`, installing dependencies from `requirements.txt` and exposing port 8000.
  - **Frontend:** Multi-stage build using Node.js to `npm run build`, and an `nginx:alpine` image to serve the static `dist/` folder.

### D. Security & Multi-Tenancy Isolation
- Production deployments must strictly enforce Row-Level Security (RLS) in PostgreSQL or isolate database schemas per tenant/workspace to guarantee that injected SQL from the LLM cannot access another user's data.

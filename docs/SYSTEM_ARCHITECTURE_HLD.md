# High-Level System Architecture (HLD)

## System Overview
The Excel AI Server is a multi-tier, AI-driven data analytics platform. It allows users to upload raw tabular data (Excel, CSV) or connect to external databases (via ETL), converts that data into an optimized analytical format in PostgreSQL, and provides a Conversational Agent (Tri-Agent) to query, visualize, and build dashboards using Natural Language.

---

## 1. High-Level Component Diagram

```mermaid
graph TD
    %% Client Tier
    Client[Vue 3 Client (SPA)]
    Share[Public Shared Dashboards]

    %% Application Tier (FastAPI)
    subgraph FastAPI Backend
        API[API Router Layer]
        Auth[JWT Auth & Security]
        Agent[Hybrid Tri-Agent System]
        ETL[ETL & Ingestion Engine]
    end

    %% AI / Observability Tier
    LLM[LLM Provider (OpenAI / Ollama)]
    Langfuse[Langfuse Observability]

    %% Data / Storage Tier
    subgraph Data Layer
        PG[(PostgreSQL + pgvector)]
        Redis[(Redis Cache)]
        Files[(File Storage / S3)]
    end

    %% Connections
    Client <-->|HTTPS / REST / SSE| API
    Share <-->|HTTPS (Read-only)| API
    
    API --> Auth
    API --> Agent
    API --> ETL
    
    Agent <-->|Prompts & SQL| LLM
    Agent -->|Traces & Metrics| Langfuse
    
    Agent <-->|SQL Execution| PG
    Agent <-->|Semantic Caching| Redis
    
    ETL <-->|Ingest raw data| Files
    ETL <-->|Store structured tables| PG
```

---

## 2. Component Interactions

### A. The Client Tier (Frontend)
- **Framework:** Vue 3 / Vite.
- **Responsibility:** Manages user sessions, renders interactive dashboards (using `ChartViewer.vue`), and provides a chat interface for natural language querying.
- **Communication:** Communicates with the backend exclusively via HTTPS REST APIs. Uses Server-Sent Events (SSE) for streaming long-running AI responses and large file upload progress.

### B. The Application Tier (FastAPI Backend)
- **API Router Layer:** Routes HTTP requests (e.g., `/api/workspaces`, `/api/etl`) to the appropriate core business logic.
- **Auth Layer:** Uses stateless JWT tokens. Verifies user identity and permissions before allowing access to workspace data.
- **Agent System:** The core natural language processor. Translates user text into SQL, executes it against PostgreSQL, and formats the output (detailed in `AI_AGENT_ARCHITECTURE_REPORT.md`).
- **ETL Engine:** Handles asynchronous data ingestion. Reads Pandas DataFrames, sanitizes column names, infers data types, and pushes structured tables into PostgreSQL.

### C. The Data Tier (Storage)
- **PostgreSQL:** The absolute source of truth.
  - **Relational Data:** Stores Users, Workspaces, Projects, and Metadata.
  - **Analytical Data:** Stores the actual ingested user datasets (e.g., `workspace_123_sales_data`).
  - **Vector Data:** Uses the `pgvector` extension to store embeddings for semantic search, synonyms, and LLM RAG pipelines.
- **Redis:** Acts as a high-speed Semantic Cache. Stores embeddings of previous queries to return instant results without re-querying the LLM.

### D. The AI & Observability Tier
- **LLM Providers:** Can route queries to OpenAI (GPT-4) for complex SQL generation, or to local Ollama models for privacy-sensitive deployments.
- **Langfuse:** Embedded deep into the FastAPI decorators. Traces every LLM call, measures token usage, latency, and costs. Integrates with the frontend via SSO tokens to allow users to view their own AI execution traces.

---

## 3. Data Flow: From File to Dashboard

1. **Upload:** User uploads `financials.xlsx` via the Vue Client.
2. **Ingestion (ETL):** FastAPI receives the file, loads it into a `pandas.DataFrame`, cleans missing values, and uses `to_sql()` to create a physical table in PostgreSQL.
3. **Profiling:** A background job runs basic statistical profiling (min, max, mean) and saves the metadata.
4. **Query:** User types "Show revenue by quarter".
5. **AI Routing:** The Hybrid Agent intercepts the query, generates PostgreSQL SQL, and executes it against the newly created financials table.
6. **Rendering:** The result set is passed to the Plot Agent, which wraps it in a Recharts-compatible JSON schema. The Vue client renders the dashboard widget.

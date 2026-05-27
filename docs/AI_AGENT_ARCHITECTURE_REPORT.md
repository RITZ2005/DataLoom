# AI & Agent Core Architecture Report — `app/core/`

## Executive Summary
This document provides a deep dive into the "brain" of the Excel AI Server API. The AI architecture employs a **Tri-Agent Routing System** that intercepts natural language queries, detects intent via a semantic router, and delegates execution to specialized LangChain-powered execution paths. It also outlines the Retrieval-Augmented Generation (RAG) and Semantic Vector caching logic.

---

## 1. Core Abstractions & The Hybrid Agent (`app/core/agent.py`)
The `HybridAgent` is the main entry point for natural language querying across the application (used heavily by `/api/query` and `/api/workspaces/.../chat`).

- **Base Architecture:** Implements a Mixin pattern to keep the massive logic clean.
- **`RoutingMixin` (`routing.py`):** Intercepts queries to perform semantic caching lookups and intent detection. It asks a lightweight LLM (or uses local heuristics) to classify a query into:
  - `metadata`: Asking about columns, shapes, dataset info.
  - `plot`: Asking for a chart or data visualization.
  - `analytical`: Asking for numeric summaries, trends, or specific data rows.
  - `general`: Chit-chat or unrelated questions.
- **Cache Layer:** Semantic caching uses RediSearch or `pgvector` to find semantically similar previous queries and return immediate, cached results to drastically reduce LLM costs and latency.

## 2. The Execution Paths (`app/core/paths/`)
Once the intent is determined, the agent delegates the actual work to a specialized Path executor.

### A. The Analytical / SQL Agent (`analytical.py` / `sql_agent.py`)
- **Role:** Generates syntactically correct SQL queries (PostgreSQL/MySQL) against the user's workspace tables.
- **Process:** 
  1. Pulls the workspace's Database Schema.
  2. Embeds the user's schema alongside the `query` into an LLM prompt.
  3. Uses LangChain's SQLDatabase Toolkit (or a custom wrapper) to let the LLM generate a `SELECT` query.
  4. Validates the SQL to prevent mutations (`DROP`, `INSERT`, `UPDATE`).
  5. Executes the SQL using the `WorkspaceSqlAgent`.
  6. Returns the raw JSON data and the generated SQL to the user.

### B. The Plot Agent (`plot.py`)
- **Role:** Transforms data into standardized chart configurations readable by the frontend's `ChartViewer.vue`.
- **Process:**
  1. Often chains *after* the Analytical agent (gets the SQL output data).
  2. The LLM is prompted to determine the best visual representation (`bar`, `line`, `pie`, `scatter`).
  3. Maps the resulting data columns to `x_axis`, `y_axis`, and `series_by`.
  4. Outputs a strict JSON schema conforming to `ChartSchema`.

### C. The Metadata Agent (`metadata.py`)
- **Role:** Answers questions about the data structure without executing heavy SQL calculations.
- **Process:** Reads the Pandas Profiling or database introspection data (from `profiler.py`) and returns a plain text/markdown explanation.

## 3. Advanced Components

### `workspace_sql.py` (The Heavy Lifter)
This module encapsulates the multi-tenant SQL generation logic.
- **Security:** Injects Row-Level Security (RLS) or strictly binds SQL execution to specific `workspace_id` prefixes to prevent cross-tenant data leaks.
- **Semantic Layer Integration:** Pulls custom Dimensions, Metrics, and Synonyms from the workspace catalog (e.g., if a user asks for "Net Profit", it replaces it with the underlying SQL formula `Revenue - Costs`).
- **Dynamic Aggregation:** Heuristically decides when to `GROUP BY` versus returning raw rows, optimizing for the frontend's table/chart views.

### `llm.py` & Embeddings
- **LLM Abstraction:** A wrapper around `langchain_core`. Provides `invoke_llm_with_retry` to handle rate limits and transient errors from OpenAI/Ollama.
- **Embeddings (`embeddings.py`):** Uses custom `OpenWebUIEmbeddings` or `langchain-openai` embeddings to convert natural language queries into vectors. Used for:
  1. Semantic Caching.
  2. RAG on unstructured data (if documents are uploaded).
  3. Finding semantic synonyms in the Workspace Catalog.

---

## 4. Sequence Flow: "Show me sales by region"
1. **Frontend:** `POST /api/workspaces/{id}/chat` -> `query="Show me sales by region"`
2. **HybridAgent:** Hits `RoutingMixin`. Detects intent: `plot`.
3. **Cache:** Checks Vector DB for "sales by region". *Miss*.
4. **Analytical Path:** Sends schema to LLM. LLM generates: `SELECT region, SUM(sales) FROM w_{id}_sales GROUP BY region`.
5. **Execution:** Runs SQL. Result: `[{region: "US", sum: 100}, ...]`.
6. **Plot Path:** LLM converts result to Chart Configuration (Bar chart, X=region, Y=sum).
7. **Return:** Data + Chart Config + Generated SQL returned to frontend.
8. **Cache:** Result cached in Vector DB.

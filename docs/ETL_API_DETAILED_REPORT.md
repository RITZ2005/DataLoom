# ETL Router — Detailed API Endpoint Documentation

> **Source File:** `app/routers/etl.py`  
> **Prefix:** `/api/etl`  
> **Auth:** All endpoints require `Bearer` JWT token via `get_current_user`.  
> **Database Tables Used:** `etl_system.etl_connections`, `etl_system.etl_jobs`, `etl_system.etl_tables`

---

## 1. `POST /api/etl/connect`

**What it does:**  
Connects to an external database (MySQL, PostgreSQL, or MongoDB), validates the connection, discovers all available tables/collections, and persists the connection credentials for reuse. If a `connection_id` is provided, it reconnects using saved credentials instead of requiring fresh input.

**Why it exists (Business Logic):**  
The frontend ETL Wizard (Step 1) needs to let users enter their external database credentials, verify the connection is live, and display a list of available tables so the user can select which ones to import. Saved connections allow users to reconnect without re-entering credentials every time.

**Dependencies:**
- `app.core.etl.connectors.factory.create_connector()` — Factory that returns `SQLConnector` or `MongoConnector`
- `app.core.etl.connectors.base_connector.ConnectionConfig` — Dataclass holding credentials
- **DB Table:** `etl_system.etl_connections` — INSERT new / UPDATE `last_used_at` for existing
- **In-memory cache:** `_active_connectors` dict — caches live connector instances by `connection_id`

**Constraints & Validations:**
- Pydantic `model_validator`: Must provide either `connection_id` OR (`db_type` + `database` + credentials)
- Connection test must pass (`connector.test_connection()`) or 400 is raised
- Passwords are stored in **plaintext** (production should use encryption)

**Expected Payload:**
```json
{
  "connection_id": null,
  "db_type": "postgresql",
  "host": "localhost",
  "port": 5432,
  "username": "postgres",
  "password": "postgres",
  "database": "sample_db",
  "auth_source": "admin",
  "connection_name": "Local PG"
}
```

**Success Response:**
```json
{
  "connection_id": "a1b2c3d4-...",
  "db_type": "postgresql",
  "database": "sample_db",
  "tables": [
    {
      "name": "orders",
      "row_count": 15000,
      "columns": [{"name": "id", "type": "INTEGER"}, {"name": "total", "type": "NUMERIC"}]
    }
  ],
  "message": "Connected successfully"
}
```

**Possible Errors:**
- `400` — Connection test failed (wrong credentials, host unreachable)
- `404` — Provided `connection_id` not found in DB
- `500` — Unexpected driver/network error

---

## 2. `POST /api/etl/preview-table`

**What it does:**  
Fetches a small sample of rows (default 50, max 200) from a specific table in the connected external database. Returns the rows as a list of dictionaries plus column names.

**Why it exists (Business Logic):**  
Before committing to a full ETL extraction, users need to visually inspect the data structure and content of each table. The frontend renders this as a data grid in the "Select Tables" step of the wizard.

**Dependencies:**
- `_get_or_restore_connector()` — Retrieves or rebuilds the connector from saved credentials
- `connector.preview_table()` — Runs `SELECT * ... LIMIT N` (SQL) or `cursor.find().limit(N)` (Mongo)
- Uses JSON roundtrip serialization to safely handle numpy types and NaN values

**Constraints & Validations:**
- `limit` field: max 200 (enforced by Pydantic `le=200`)
- `connection_id` must exist and belong to the current user

**Expected Payload:**
```json
{
  "connection_id": "a1b2c3d4-...",
  "table_name": "orders",
  "limit": 50
}
```

**Success Response:**
```json
{
  "table_name": "orders",
  "rows": [
    {"id": 1, "customer": "Acme Corp", "total": 4500.00},
    {"id": 2, "customer": "Globex", "total": 1200.50}
  ],
  "total_rows": 2,
  "columns": ["id", "customer", "total"]
}
```

**Possible Errors:**
- `404` — Connection not found or not owned by user
- `400` — Saved connection failed reconnection test
- `500` — Query execution error (e.g., table doesn't exist, permission denied)

---

## 3. `POST /api/etl/dry-run`

**What it does:**  
Executes the complete ETL pipeline on only 100 rows as a quick validation. It extracts a sample from the source DB, writes it to temporary Parquet files, runs the user's Python transform script inside an isolated subprocess sandbox (30s timeout), and returns a preview of the transformed output.

**Why it exists (Business Logic):**  
Users need to test their custom Python transform script before committing to a full (potentially hours-long) ETL job. The dry-run catches syntax errors, logic bugs, and type mismatches on a tiny sample instantly.

**Dependencies:**
- `connector.extract_to_parquet(limit=100)` — Extracts 100-row sample to Parquet
- `ETLExecutor(timeout=30)` — Spawns `sandbox_runner.py` as isolated subprocess
- `sandbox_runner.py` — Loads Parquet → runs user `transform()` → writes output Parquet
- Temporary directory via `tempfile.mkdtemp()` — cleaned up in `finally` block
- `_normalize_extract_datasets()` — Merges legacy `table_names` + new `datasets` format

**Constraints & Validations:**
- `transform_script` is required (must contain `def transform(tables)`)
- Must provide at least one `table_name` or `dataset` (Pydantic validator)
- Sandbox timeout: **30 seconds** (shorter than full runs)
- `{{LAST_SYNC_VALUE}}` placeholders are replaced with safe defaults for dry-run

**Expected Payload:**
```json
{
  "connection_id": "a1b2c3d4-...",
  "table_names": ["orders"],
  "datasets": [],
  "transform_script": "import pandas as pd\nfrom typing import Dict\n\ndef transform(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:\n    return tables\n"
}
```

**Success Response:**
```json
{
  "success": true,
  "duration_seconds": 2.3,
  "output_tables": [
    {
      "name": "orders",
      "row_count": 100,
      "columns": ["id", "customer", "total"],
      "preview": [{"id": 1, "customer": "Acme", "total": 4500}]
    }
  ],
  "stdout": "[sandbox] Loaded 1 table(s)...\n[sandbox] Transform complete!"
}
```

**Possible Errors:**
- `success: false` with `error` field — Transform script crashed (syntax error, type mismatch, etc.)
- `success: false` with timeout message — Script took longer than 30s (infinite loop)
- The endpoint returns 200 even on failure; check the `success` boolean in the response body

---

## 4. `POST /api/etl/execute-job`

**What it does:**  
Submits a full ETL pipeline job that runs as a **background task**. It creates a job record in `etl_system.etl_jobs` with status `pending`, then dispatches the 3-phase pipeline (Extract → Transform → Load) to run asynchronously. Returns the `job_id` immediately for frontend polling.

**Why it exists (Business Logic):**  
Full ETL jobs can take minutes to hours depending on data volume. The frontend needs to fire-and-forget and then poll `/api/etl/job/{job_id}` for status updates. The job system also enables re-running pipelines and tracking execution history.

**Dependencies:**
- `FastAPI BackgroundTasks` — Dispatches `_run_full_etl_pipeline()` asynchronously
- `_run_full_etl_pipeline()` — Internal function that orchestrates Extract/Transform/Load
- `ETLExecutor` — Sandbox subprocess (default 120s timeout)
- `ETLLoader.load_to_postgres()` — Bulk-loads Parquet into workspace PostgreSQL schema
- `_auto_profile_workspace_tables()` — Auto-profiles loaded tables for AI query routing
- **DB Tables:** `etl_system.etl_jobs` (INSERT/UPDATE), `etl_system.etl_tables` (via loader)
- `get_workspace_schema_name()` — Resolves `ws_{workspace_id}` schema name

**Constraints & Validations:**
- `workspace_id` is **required** (400 if missing)
- `sync_mode` must be `"overwrite"` or `"append"` (Pydantic validator)
- Must provide at least one `table_name` or `dataset`
- If `job_id` is provided, it updates an existing job record (re-run mode)

**Expected Payload:**
```json
{
  "job_id": null,
  "connection_id": "a1b2c3d4-...",
  "table_names": ["orders"],
  "datasets": [],
  "transform_script": "import pandas as pd\nfrom typing import Dict\n\ndef transform(tables):\n    return tables\n",
  "target_table": "orders_clean",
  "pipeline_name": "Orders Pipeline",
  "sync_mode": "overwrite",
  "sync_column": null,
  "primary_keys": null,
  "workspace_id": "ws-uuid-123"
}
```

**Success Response:**
```json
{
  "job_id": "job-uuid-456",
  "status": "pending",
  "message": "Job submitted successfully"
}
```

**Possible Errors:**
- `400` — Missing `workspace_id`, invalid `sync_mode`, no tables provided
- `404` — Provided `job_id` not found or not owned by user (re-run mode)
- `500` — Connector restoration failure

---

## 5. `GET /api/etl/job/{job_id}`

**What it does:**  
Returns the current status and metadata of an ETL job. The frontend polls this endpoint every few seconds after submitting a job to track progress through the pipeline phases: `pending → extracting → transforming → loading → complete/failed`.

**Why it exists (Business Logic):**  
Since ETL jobs run in the background, the frontend needs a polling mechanism to display real-time progress bars and status indicators. On completion, the response includes `output_tables` metadata so the UI can show what was loaded.

**Dependencies:**
- **DB Table:** `etl_system.etl_jobs` — SELECT by `job_id`

**Constraints & Validations:**
- `job_id` path parameter is required
- No ownership check currently (any authenticated user can view any job)

**Expected Payload:** None (GET request, `job_id` in URL path)

**Success Response:**
```json
{
  "job_id": "job-uuid-456",
  "status": "complete",
  "source_tables": [{"table_name": "orders"}],
  "output_tables": [{"table_name": "orders_clean", "row_count": 15000, "schema_name": "ws_abc"}],
  "error_message": null,
  "started_at": "2026-04-08 10:00:00",
  "completed_at": "2026-04-08 10:02:30",
  "target_table": "orders_clean",
  "sync_mode": "overwrite",
  "high_water_mark": null,
  "sync_column": null,
  "pipeline_name": "Orders Pipeline"
}
```

**Possible Errors:**
- `404` — Job ID not found in database

---

## 6. `GET /api/etl/connection/{connection_id}/jobs`

**What it does:**  
Lists all previously created pipeline jobs for a specific connection, ordered by creation date (newest first). Includes job status, source/output table metadata, sync configuration, and derived pipeline names.

**Why it exists (Business Logic):**  
The frontend "My Databases" page needs to show all pipelines associated with a specific database connection so users can re-run, edit, or sync them. The pipeline name derivation logic ensures every job has a human-readable label even if the user didn't explicitly name it.

**Dependencies:**
- **DB Table:** `etl_system.etl_jobs` — SELECT by `connection_id` + `created_by`

**Constraints & Validations:**
- Ownership enforced: only returns jobs created by the current user
- Pipeline name fallback chain: `pipeline_name` → first source `output_name`/`table_name` → `"Pipeline {id[:8]}"`

**Expected Payload:** None (GET request, `connection_id` in URL path)

**Success Response:**
```json
[
  {
    "job_id": "job-uuid-456",
    "status": "complete",
    "source_tables": [{"table_name": "orders"}],
    "output_tables": [{"table_name": "orders_clean", "row_count": 15000}],
    "created_at": "2026-04-08 10:00:00",
    "completed_at": "2026-04-08 10:02:30",
    "target_table": "orders_clean",
    "sync_mode": "overwrite",
    "high_water_mark": null,
    "sync_column": null,
    "sync_mode_type": "hwm",
    "pipeline_name": "Orders Pipeline"
  }
]
```

**Possible Errors:**
- Returns empty array `[]` if no jobs exist (not a 404)

---

## 7. `POST /api/etl/job/{job_id}/sync`

**What it does:**  
Performs an incremental/delta sync for an existing pipeline. It reads the pipeline's saved configuration, determines the high-water mark (the MAX value of the sync column in the target table), substitutes `{{LAST_SYNC_VALUE}}` in the original query with the actual value, extracts only new/changed rows, runs the transform, and appends the results to the existing target table.

**Why it exists (Business Logic):**  
After the initial full load, users need to periodically pull only new data from the source database without re-extracting everything. This is critical for large datasets where a full reload would take hours. Supports both High-Water Mark (HWM) mode (timestamp/ID-based) and Flag mode (query-based filtering).

**Dependencies:**
- `_get_or_restore_connector()` — Rebuilds source DB connection
- `ETLLoader.get_max_value()` — Queries `MAX(sync_column)` from the target table
- `ETLExecutor` — Sandbox subprocess for transform
- `ETLLoader.load_to_postgres(replace=False)` — Append mode loading
- `re.sub()` — Regex replacement of `{{LAST_SYNC_VALUE}}` placeholder
- **DB Tables:** `etl_system.etl_jobs` (SELECT config + UPDATE high_water_mark)

**Constraints & Validations:**
- `403` — Only the user who created the job can sync it
- `400` — Pipeline metadata corrupted, no source tables, missing sync column for HWM queries
- Supports `preview_only=true` to show what would be synced without actually loading
- Auto-infers `sync_column` from `{{LAST_SYNC_VALUE}}` query pattern if not explicitly set

**Expected Payload:**
```json
{
  "sync_column": null,
  "preview_only": false,
  "primary_keys": null
}
```

**Success Response (after load):**
```json
{
  "success": true,
  "loaded_tables": [{"table_name": "orders_clean", "row_count": 150}],
  "preview_tables": [{"table_name": "orders_clean", "row_count": 150, "columns": ["id", "total"], "preview": []}],
  "total_new_rows": 150,
  "requires_confirmation": false,
  "message": "Sync successful! Appended 150 new rows. Last sync updated to 2026-04-08 12:00:00."
}
```

**Possible Errors:**
- `404` — Pipeline job not found
- `403` — Not authorized (different user)
- `400` — Missing sync criteria, corrupted metadata, source SQL error

---

## 8. `GET /api/etl/connections`

**What it does:**  
Returns a list of all saved external database connections for the authenticated user, including connection metadata like host, port, database name, and timestamps.

**Why it exists (Business Logic):**  
The ETL Wizard dropdown needs to show previously saved connections so users can quickly reconnect without re-entering credentials. Also used by the "My Databases" page.

**Dependencies:**
- **DB Table:** `etl_system.etl_connections` — SELECT by `created_by`

**Constraints & Validations:**
- Ownership enforced: only returns connections created by the current user
- Passwords are **not** returned in the response (only metadata)

**Expected Payload:** None (GET request)

**Success Response:**
```json
{
  "connections": [
    {
      "connection_id": "a1b2c3d4-...",
      "name": "Local PG",
      "db_type": "postgresql",
      "host": "localhost",
      "port": 5432,
      "database_name": "sample_db",
      "created_at": "2026-04-07 09:00:00",
      "last_used_at": "2026-04-08 15:00:00"
    }
  ]
}
```

**Possible Errors:**
- Returns `{"connections": []}` if none exist (not a 404)

---

## 9. `DELETE /api/etl/connections/{connection_id}`

**What it does:**  
Permanently removes a saved ETL connection from the database and evicts it from the in-memory connector cache. The deletion is scoped to the current user — you cannot delete another user's connections.

**Why it exists (Business Logic):**  
Users need to clean up stale or unused database connections from their saved list. The frontend "My Databases" page has a delete button for each connection entry.

**Dependencies:**
- **DB Table:** `etl_system.etl_connections` — DELETE by `connection_id` + `created_by`
- **In-memory cache:** `_active_connectors.pop()` — removes cached connector instance

**Constraints & Validations:**
- Ownership enforced: `created_by = current_user_id`
- If `rowcount == 0` after DELETE, raises 404 (connection not found or not owned)

**Expected Payload:** None (DELETE request, `connection_id` in URL path)

**Success Response:**
```json
{
  "message": "Connection deleted",
  "connection_id": "a1b2c3d4-..."
}
```

**Possible Errors:**
- `404` — Connection not found or not owned by the current user

---

## 10. `GET /api/etl/datasets`

**What it does:**  
Returns a hierarchical view of all ETL data that has been loaded into the system, grouped by Connection → Job → Tables. Only includes connections/jobs that have actually produced output tables (empty jobs are filtered out).

**Why it exists (Business Logic):**  
The "My Databases" page needs a tree-view of all imported data: which connections exist, which pipeline jobs ran under each connection, and which tables were loaded by each job. This gives users a complete inventory of their ETL-imported datasets.

**Dependencies:**
- **DB Tables:** `etl_system.etl_connections`, `etl_system.etl_jobs`, `etl_system.etl_tables` — 3 separate SELECT queries joined in Python
- Pydantic models: `ETLDatasetConnection`, `ETLDatasetJob`, `ETLDatasetTable`

**Constraints & Validations:**
- Ownership enforced across all 3 queries via `created_by`
- Connections with zero loaded tables are excluded from the response
- `column_stats` field is auto-parsed from JSON string if stored as text

**Expected Payload:** None (GET request)

**Success Response:**
```json
{
  "connections": [
    {
      "connection_id": "a1b2c3d4-...",
      "name": "Local PG",
      "db_type": "postgresql",
      "database_name": "sample_db",
      "jobs": [
        {
          "job_id": "job-uuid-456",
          "status": "complete",
          "started_at": "2026-04-08 10:00:00",
          "completed_at": "2026-04-08 10:02:30",
          "tables": [
            {
              "table_id": "tbl-uuid",
              "table_name": "orders_clean",
              "source_name": "orders",
              "row_count": 15000,
              "column_stats": {"id": {"type": "int64"}, "total": {"type": "float64"}},
              "created_at": "2026-04-08 10:02:30"
            }
          ]
        }
      ]
    }
  ]
}
```

**Possible Errors:**
- Returns `{"connections": []}` if no datasets exist (not a 404)

---

## 11. `POST /api/etl/sync-update`

**What it does:**  
Performs a one-shot sync/append operation from a source database into an existing target table in a workspace schema. Unlike `/job/{job_id}/sync` which uses a saved pipeline's configuration, this endpoint accepts all parameters fresh — making it suitable for ad-hoc sync operations without a pre-existing pipeline job.

**Why it exists (Business Logic):**  
Provides a simpler, stateless alternative to the full delta-sync flow. Used when the frontend needs to quickly append new data from a source table into an already-loaded workspace table without creating or referencing a formal pipeline job record.

**Dependencies:**
- `connector.extract_to_parquet()` — Extracts source data
- `ETLExecutor` — Runs transform (uses identity transform if no script provided)
- `ETLLoader.load_to_postgres(replace=False)` — Append mode
- `get_workspace_schema_name()` — Resolves target schema

**Constraints & Validations:**
- `workspace_id` is **required** (400 if missing)
- `target_table_name` is **required**
- Must provide at least one `table_name` or `dataset`
- If `transform_script` is null, a passthrough identity script is generated automatically

**Expected Payload:**
```json
{
  "connection_id": "a1b2c3d4-...",
  "workspace_id": "ws-uuid-123",
  "target_table_name": "orders_clean",
  "table_names": ["orders"],
  "datasets": [],
  "transform_script": null
}
```

**Success Response:**
```json
{
  "success": true,
  "loaded_tables": [{"table_name": "orders_clean", "row_count": 500, "schema_name": "ws_abc"}],
  "preview_tables": [],
  "total_new_rows": 0,
  "requires_confirmation": false,
  "message": "Sync update completed"
}
```

**Possible Errors:**
- `400` — Missing `workspace_id`, no datasets, transform script failed
- `404` — Connection not found
- `500` — Extraction or loading failure

---

## 12. `POST /api/etl/generate-transform`

**What it does:**  
Uses GPT-4o (via LangChain's `ChatOpenAI`) to automatically generate a Python transform script based on a natural language prompt and the available table schemas. Returns raw Python code ready to be pasted into the ETL wizard's code editor.

**Why it exists (Business Logic):**  
Many users are not Python developers. This AI-powered feature lets them describe their desired transformation in plain English (e.g., "normalize date columns and remove duplicates") and receive a working `transform()` function automatically.

**Dependencies:**
- `langchain_openai.ChatOpenAI` — GPT-4o with `temperature=0.2`
- OpenAI API key (from environment)
- Table schema metadata from `TableInfo` models

**Constraints & Validations:**
- `prompt` is required (the natural language instruction)
- `tables` list is required (provides schema context to the LLM)
- The LLM is instructed to return only raw Python code (no markdown fencing)
- Response code is post-processed to strip any accidental markdown formatting

**Expected Payload:**
```json
{
  "prompt": "Normalize date columns and remove duplicates",
  "tables": [
    {
      "name": "orders",
      "row_count": 1000,
      "columns": [
        {"name": "id", "type": "INTEGER"},
        {"name": "order_date", "type": "VARCHAR"},
        {"name": "total", "type": "NUMERIC"}
      ]
    }
  ]
}
```

**Success Response:**
```json
{
  "script": "import pandas as pd\nfrom typing import Dict\n\ndef transform(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:\n    if 'orders' in tables:\n        df = tables['orders']\n        df['order_date'] = pd.to_datetime(df['order_date'])\n        df = df.drop_duplicates()\n        tables['orders'] = df\n    return tables\n"
}
```

**Possible Errors:**
- `500` — OpenAI API key missing, rate limit, or LLM generation error

---

## 13. `PATCH /api/etl/job/{job_id}/sync-config`

**What it does:**  
Updates the sync configuration fields (`sync_column`, `sync_mode_type`, `pipeline_name`) on an existing pipeline job record without re-running the pipeline. This is a lightweight metadata-only update.

**Why it exists (Business Logic):**  
After creating a pipeline, users may want to change the sync strategy (e.g., switch from HWM mode to Flag mode) or rename the pipeline without going through the full re-execution flow. The frontend pipeline settings panel uses this endpoint.

**Dependencies:**
- **DB Table:** `etl_system.etl_jobs` — UPDATE selective columns

**Constraints & Validations:**
- Ownership enforced: `created_by = current_user_id`
- `sync_mode_type` must be `'hwm'` or `'flag'` if provided (400 otherwise)
- At least one field must be provided (400 if all are null)
- 404 if `rowcount == 0` after UPDATE

**Expected Payload:**
```json
{
  "sync_column": "updated_at",
  "sync_mode_type": "hwm",
  "pipeline_name": "Orders Daily Sync"
}
```

**Success Response:**
```json
{
  "message": "Sync config updated",
  "job_id": "job-uuid-456"
}
```

**Possible Errors:**
- `400` — Invalid `sync_mode_type`, no fields to update
- `404` — Pipeline not found or not owned by user

---

## 14. `GET /api/etl/job/{job_id}/detail`

**What it does:**  
Returns the full configuration of a pipeline job including source tables, transform script, target table, sync settings, and workspace routing. This is a read-only endpoint that provides everything needed to pre-fill the "Edit Pipeline" wizard in the frontend.

**Why it exists (Business Logic):**  
When a user clicks "Edit" on an existing pipeline, the frontend needs to reconstruct the entire wizard state (connection, tables, script, sync config). This endpoint provides all the saved configuration in one call.

**Dependencies:**
- **DB Table:** `etl_system.etl_jobs` — SELECT by `job_id` + `created_by`

**Constraints & Validations:**
- Ownership enforced: only the creator can view job details
- `source_tables` is auto-parsed from JSON string if stored as text
- `primary_keys` is auto-parsed from JSON string
- `sync_mode_type` defaults to `'hwm'` if null

**Expected Payload:** None (GET request, `job_id` in URL path)

**Success Response:**
```json
{
  "job_id": "job-uuid-456",
  "connection_id": "a1b2c3d4-...",
  "source_tables": [{"table_name": "orders", "sync_column": "updated_at"}],
  "transform_script": "import pandas as pd\n...",
  "target_table": "orders_clean",
  "sync_mode": "overwrite",
  "sync_column": "updated_at",
  "sync_mode_type": "hwm",
  "workspace_id": "ws-uuid-123",
  "pipeline_name": "Orders Pipeline",
  "primary_keys": ["id"]
}
```

**Possible Errors:**
- `404` — Pipeline not found or not owned by user

---

## 15. `PUT /api/etl/job/{job_id}`

**What it does:**  
Updates an existing pipeline job's configuration fields in-place without triggering a re-execution. Supports partial updates — only the provided fields are modified. This is a heavier version of `PATCH /sync-config` that covers all job fields including `source_tables`, `transform_script`, `target_table`, and `primary_keys`.

**Why it exists (Business Logic):**  
The "Edit Pipeline" wizard saves its changes through this endpoint. After a user modifies their table selections, transform script, or sync settings, the frontend PUTs the updated configuration. The pipeline can then be re-executed separately via `POST /execute-job` with the same `job_id`.

**Dependencies:**
- **DB Table:** `etl_system.etl_jobs` — UPDATE selective columns dynamically

**Constraints & Validations:**
- Ownership enforced: `created_by = current_user_id`
- `sync_mode_type` must be `'hwm'` or `'flag'` if provided
- At least one field must be provided (400 if all are null)
- `source_tables` and `primary_keys` are serialized to JSON before storage

**Expected Payload:**
```json
{
  "source_tables": [{"table_name": "orders", "sync_column": "updated_at"}],
  "transform_script": "import pandas as pd\n...",
  "target_table": "orders_v2",
  "sync_mode": "append",
  "sync_column": "updated_at",
  "sync_mode_type": "hwm",
  "pipeline_name": "Orders V2",
  "primary_keys": ["id"]
}
```

**Success Response:**
```json
{
  "message": "Pipeline updated",
  "job_id": "job-uuid-456"
}
```

**Possible Errors:**
- `400` — Invalid `sync_mode_type`, no fields to update
- `404` — Pipeline not found or not owned by user
